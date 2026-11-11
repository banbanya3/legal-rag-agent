"""一键初始化脚本。

用法（在 backend 目录下执行）：

    python init_knowledge.py                # 建库建表 + 显示当前状态
    python init_knowledge.py --build        # 增量构建全部法律索引（推荐首次运行）
    python init_knowledge.py --build --force  # 删掉重建（改了切分参数时用）
    python init_knowledge.py --domain labor --build
    python init_knowledge.py --reset        # 清空向量库和法条表，回到初始状态
    python init_knowledge.py --check        # 只体检，不写任何数据

为什么索引构建不放在启动时自动做：
30 多份文档、上千条切片，全部走一遍 embedding 接口要花几分钟和一笔真金白银。
这种"一次性、有成本"的操作必须由人显式触发，而不是每次重启都偷偷跑一遍。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from common.logger import get_logger
from config import LAW_DOMAINS, UPLOAD_COLLECTION, collection_name, settings
from dao import knowledge_dao, statute_dao
from dao.db import create_tables, ensure_database, session_scope
from rag import indexer, milvus_store
from service import knowledge_service

logger = get_logger("init")


def cmd_status() -> None:
    """打印知识库现状。没建索引时也能跑，用来确认文件是不是都放对了位置。"""
    print("\n" + "=" * 74)
    print("  知识库状态")
    print("=" * 74)
    print(f"  {'领域':<12}{'目录':<14}{'文档':>5}{'切片':>8}{'法条':>7}")
    print("-" * 74)

    total_docs = total_chunks = total_articles = 0
    for key, meta in LAW_DOMAINS.items():
        files = indexer.list_domain_files(key)
        vectors = milvus_store.count(collection_name(key))
        total_docs += len(files)
        total_chunks += vectors
        print(
            f"  {meta['label']:<12}{meta['dir']:<14}{len(files):>5}{vectors:>8}"
        )
    print("-" * 74)

    with session_scope() as db:
        total_articles = statute_dao.count_all(db)
        uploads = knowledge_dao.count_docs(db)

    print(f"  合计：{total_docs} 份文档 / {total_chunks} 条向量切片 / "
          f"{total_articles} 条结构化法条")
    print(f"  上传文档：{len(list(settings.UPLOAD_DIR.glob('*')))} 个文件")
    print(f"  Milvus  ：{settings.MILVUS_URI}")
    print(f"  存储占用：{knowledge_service.storage_size_mb()} MB")
    print("=" * 74 + "\n")


def cmd_reset() -> None:
    """清空向量集合 + 法条表 + 台账，回到"什么都没索引"的状态。"""
    print("⚠️  即将清空全部向量集合与法条表，源文件不会受影响。")
    confirm = input("确认请输入 yes：").strip().lower()
    if confirm != "yes":
        print("已取消。")
        return

    for key in LAW_DOMAINS:
        milvus_store.drop(collection_name(key))
    milvus_store.drop(UPLOAD_COLLECTION)

    from dao.models import KnowledgeDoc, StatuteArticle
    from dao.db import SessionLocal

    db = SessionLocal()
    try:
        db.query(StatuteArticle).delete()
        db.query(KnowledgeDoc).delete()
        db.commit()
    finally:
        db.close()

    print("✅ 已清空。重新构建请执行：python init_knowledge.py --build")


def cmd_build(domain: str | None, force: bool) -> None:
    print(f"\n开始构建索引（domain={domain or '全部'}, force={force}）\n")
    result = knowledge_service.build(domain=domain, force=force)

    for item in result["domains"]:
        flag = "" if not item["failed"] else f"  ⚠️ {len(item['failed'])} 个失败"
        print(
            f"  ✓ {item['label']:<12} {item['files']:>2} 个文件  "
            f"{item['chunks']:>4} 切片  {item['articles']:>4} 法条{flag}"
        )
        for fail in item["failed"]:
            print(f"      ✗ {fail['filename']}: {fail['reason']}")

    print(f"\n{result['message']}\n")


def cmd_check() -> None:
    """环境体检：把最容易出问题的几项挨个验一遍。"""
    print("\n环境体检\n" + "-" * 50)

    ok = True

    # 1. 配置文件
    env_file = BACKEND_DIR / ".env"
    print(f"  .env 文件        : {'存在' if env_file.exists() else '缺失 ❌'}")
    ok &= env_file.exists()

    # 2. API Key
    has_key = bool(settings.LLM_API_KEY and "your-" not in settings.LLM_API_KEY)
    print(f"  LLM API Key      : {'已配置' if has_key else '未配置 ❌'}")
    ok &= has_key

    # 3. MySQL
    from dao.db import ping
    mysql_ok, mysql_msg = ping()
    print(f"  MySQL            : {'正常' if mysql_ok else '异常 ❌'}  {mysql_msg[:60]}")
    ok &= mysql_ok

    # 4. Milvus Lite
    #    注意：Milvus Lite 是"单进程独占"的嵌入式数据库，后端服务在跑的时候，
    #    这个脚本打不开同一个数据目录。这不是故障，是设计使然。
    try:
        client = milvus_store.get_client()
        collections = client.list_collections()
        print(f"  Milvus           : 正常（{len(collections)} 个集合）")
    except Exception as exc:  # noqa: BLE001
        name = type(exc).__name__
        detail = str(exc).lower()
        locked = (
            "locked" in name.lower()
            or "locked" in detail
            or "open local milvus failed" in detail
            or "permission" in detail
        )
        if locked:
            print("  Milvus           : 被占用（后端正在运行）")
            print("                     重建索引前请先停掉 app.py —— Milvus Lite 是")
            print("                     单进程独占的嵌入式库，两个进程不能同时打开。")
        else:
            print(f"  Milvus           : 异常 ❌  {name}: {exc}")
            ok = False

    # 5. 知识库文件
    total_files = sum(len(indexer.list_domain_files(key)) for key in LAW_DOMAINS)
    print(f"  法律知识文件     : {total_files} 份")
    ok &= total_files > 0

    print("-" * 50)
    print("  结论：" + ("全部通过 ✅" if ok else "存在待修复项 ❌") + "\n")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description="法律知识库初始化工具")
    parser.add_argument("--build", action="store_true", help="构建索引")
    parser.add_argument("--force", action="store_true", help="先删集合再重建")
    parser.add_argument("--domain", default=None, help="只处理某个领域，如 labor")
    parser.add_argument("--reset", action="store_true", help="清空向量与法条表")
    parser.add_argument("--check", action="store_true", help="只做环境体检")
    args = parser.parse_args()

    if args.check:
        cmd_check()
        return

    # 任何操作前都先确保库和表存在
    ensure_database()
    create_tables()

    if args.reset:
        cmd_reset()
        return

    if args.build:
        cmd_build(args.domain, args.force)

    cmd_status()


if __name__ == "__main__":
    main()
