"""
全局配置中心。

设计原则：
1. 所有路径都基于 BASE_DIR 推导，绝不写死盘符，换台机器也能跑；
2. 密钥、数据库连接串一律走环境变量（.env），代码里只留可运行的默认值；
3. 知识库的"法律领域"在这里集中注册，新增一个领域只需要加一行配置，
   API / 检索 / 前端统计会自动跟着变，不用改五六个文件。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------- 路径
# __file__ = backend/config.py
#   .parent        -> backend/
#   .parent.parent -> legal-rag-agent/
BASE_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = BASE_DIR / "backend"

# 支持在 PyCharm 里直接右键 Run 任意脚本（把 backend 放进 sys.path）
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 不用 python-dotenv，自己解析 .env。三个理由：
#
# 1. 行为可预测。20 行代码，读什么就是什么，出问题能一眼看出在哪。
# 2. 优先级明确。.env 文件 > 系统环境变量 > 代码默认值，不会出现
#    "系统里有同名变量就把配置文件盖掉"这种反直觉行为（python-dotenv 默认 override=False）。
# 3. 少一个依赖。这个项目本身不需要变量插值、多行值这些高级特性。
#
# 注意：配置只在进程启动时读一次，改了 .env 必须重启后端才生效。
# 启动日志里的 `[config] key=xxxxxx***` 就是实际生效的值，排查时先看它。
def _read_env_file(path: Path) -> dict[str, str]:
    """极简 .env 解析器。

    支持：KEY=VALUE、# 注释、export 前缀、单双引号包裹。
    不支持：多行值、变量插值 —— 这个项目用不到，不引入多余的复杂度。
    """
    data: dict[str, str] = {}
    if not path.exists():
        return data

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            data[key] = value
    return data


_ENV_FILE = _read_env_file(BACKEND_DIR / ".env")


def env(key: str, default: str = "") -> str:
    """三优先级取配置：.env 文件 > 系统环境变量 > 代码默认值。

    .env 里写了空值（如 MILVUS_URI=）视为"未设置"，回落到系统环境变量或默认值，
    否则空字符串会把默认路径冲掉。
    """
    value = _ENV_FILE.get(key)
    if value:
        return value
    return os.getenv(key) or default


class Settings:
    """配置单例。全部用类属性，导入即用，不需要实例化传参。"""

    # ---------------- 目录 ----------------
    STORAGE_DIR: Path = BASE_DIR / "storage"
    KNOWLEDGE_DIR: Path = BASE_DIR / "knowledge_base"
    UPLOAD_DIR: Path = BASE_DIR / "storage" / "uploads"
    MILVUS_DIR: Path = BASE_DIR / "storage" / "milvus_lite"

    # ---------------- 大模型（智谱 GLM，OpenAI 兼容协议） ----------------
    LLM_API_KEY: str = env("LLM_API_KEY", "")
    LLM_BASE_URL: str = env("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
    LLM_MODEL: str = env("LLM_MODEL", "glm-4-flash")
    EMBED_MODEL: str = env("EMBED_MODEL", "embedding-2")
    RERANK_MODEL: str = env("RERANK_MODEL", "rerank")

    # 向量维度：embedding-2 固定 1024 维。切换 embedding 模型必须同步改这里，
    # 否则 Milvus 会因为维度不匹配直接拒绝写入。
    EMBED_DIM: int = int(env("EMBED_DIM", "1024"))

    # ---------------- Milvus ----------------
    # 传目录路径 -> Milvus Lite（嵌入式，进程内启动，零运维）
    # 传 http://host:19530 -> Milvus Standalone（Docker 部署，多进程共享）
    #
    # 注意这里用 `or` 而不是 getenv 的默认值：.env 里写了 MILVUS_URI= 时，
    # getenv 会返回空字符串（不是 None），默认值根本不会生效。
    MILVUS_URI: str = env("MILVUS_URI") or str(MILVUS_DIR / "legal_law.db")

    # ---------------- MySQL ----------------
    MYSQL_HOST: str = env("MYSQL_HOST", "127.0.0.1")
    MYSQL_PORT: int = int(env("MYSQL_PORT", "3306"))
    MYSQL_USER: str = env("MYSQL_USER", "root")
    MYSQL_PASSWORD: str = env("MYSQL_PASSWORD", "root")
    MYSQL_DATABASE: str = env("MYSQL_DATABASE", "legal_rag_db")

    @property
    def mysql_url(self) -> str:
        return (
            f"mysql+pymysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"
            f"?charset=utf8mb4"
        )

    @property
    def mysql_server_url(self) -> str:
        """不带库名的连接串，用于首次 CREATE DATABASE。"""
        return (
            f"mysql+pymysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/?charset=utf8mb4"
        )

    # ---------------- 检索参数 ----------------
    CHUNK_SIZE: int = int(env("CHUNK_SIZE", "420"))
    CHUNK_OVERLAP: int = int(env("CHUNK_OVERLAP", "60"))
    DEFAULT_TOP_K: int = int(env("DEFAULT_TOP_K", "8"))     # 向量粗排召回
    DEFAULT_RERANK_N: int = int(env("DEFAULT_RERANK_N", "4"))  # 精排保留

    # ---------------- 混合检索 ----------------
    # BM25 稀疏检索开关。
    #
    # ⚠️ 默认关闭 —— 这是跑完 50 条评测集后的结论，不是懒得开：
    #
    #     纯向量         Recall@4 = 0.900
    #     向量 + BM25    Recall@4 = 0.800
    #     向量 + 精排    Recall@4 = 0.800
    #     全套           Recall@4 = 0.640
    #
    # 原因：语料只有 845 条切片，向量检索已经覆盖得很好；
    # 而 BM25 对"怀孕了公司能开除我吗"这类语义改写的口语问题无能为力 ——
    # 它只能匹配字面重合，口语和法条原文之间几乎没有共同词。
    # 想对比效果就在 .env 里改成 true，代码链路是完整的。
    USE_BM25: bool = env("USE_BM25", "false").lower() == "true"
    # 每路各取多少条进融合池
    BM25_TOP_K: int = int(env("BM25_TOP_K", "8"))
    # RRF 的 k 值：越大，排名靠前的优势越平缓。60 是论文经验值
    RRF_K: int = int(env("RRF_K", "60"))
    RRF_K: int = 60  # 倒数排名融合的平滑常数，业界默认 60

    # ---------------- 上传限制 ----------------
    MAX_UPLOAD_MB: int = int(env("MAX_UPLOAD_MB", "10"))
    # 上传允许的格式。
    # .md/.txt 走结构感知切分（有「第X条」还能进法条表）；
    # .pdf/.docx 由 LlamaIndex 的 reader 提取纯文本，只做语义检索。
    ALLOWED_SUFFIXES: tuple = (".txt", ".md", ".markdown", ".pdf", ".docx")

    # ---------------- 服务 ----------------
    HOST: str = env("HOST", "127.0.0.1")
    PORT: int = int(env("PORT", "5000"))
    DEBUG: bool = env("DEBUG", "true").lower() == "true"

    # 开发期允许本地任意端口的前端访问（Vite 默认 5173）
    CORS_ORIGINS: list = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ]


settings = Settings()

# 启动时打一行配置摘要（密钥只露前 6 位）。
# 排查"改了 .env 却没生效"这类问题时，第一眼看这里最快。
# 走 stderr：MCP 服务用 stdout 传 JSON-RPC，这里不能抢。
print(
    f"[config] env={BACKEND_DIR / '.env'} | key={settings.LLM_API_KEY[:6]}*** | "
    f"model={settings.LLM_MODEL} | db={settings.MYSQL_DATABASE}",
    file=sys.stderr,
)

# ---------------------------------------------------------------- 法律领域注册表
# key 既作为 Milvus collection 名后缀，也作为知识库目录名、前端展示的分类键。
# 三处共用一份定义，避免"目录改了但代码没改"这类低级事故。
LAW_DOMAINS: dict[str, dict] = {
    "civil": {
        "label": "民事法律",
        "dir": "01_civil",
        "desc": "民法典各编、婚姻家庭、继承、合同、物权、侵权、借贷与房产纠纷",
        "tool": "检索婚姻、继承、合同、借贷、房屋、侵权赔偿等民事法律问题",
        "color": "#2f5fd0",
    },
    "labor": {
        "label": "劳动与社会保障",
        "dir": "02_labor",
        "desc": "劳动法、劳动合同法、工伤认定、社保缴纳、加班工资、劳动争议仲裁",
        "tool": "检索劳动合同、试用期、工资工时、加班费、工伤、社保、辞退赔偿等问题",
        "color": "#0f9d76",
    },
    "criminal": {
        "label": "刑事与治安",
        "dir": "03_criminal",
        "desc": "刑法常见罪名、量刑规则、正当防卫、醉驾、诈骗、治安管理处罚",
        "tool": "检索犯罪构成、量刑标准、正当防卫、醉驾、诈骗、治安处罚等问题",
        "color": "#c0392b",
    },
    "business": {
        "label": "商事与经济",
        "dir": "04_business",
        "desc": "公司法、合伙、消费者权益、食品安全、产品质量、电商与税务",
        "tool": "检索公司设立、股权、消费者维权、食品安全、产品质量、个体户与税务问题",
        "color": "#b7791f",
    },
    "digital": {
        "label": "数字与知识产权",
        "dir": "05_digital",
        "desc": "著作权、商标、专利、个人信息保护、数据安全、网络安全、反电信诈骗",
        "tool": "检索著作权、商标、专利、个人信息、数据合规、网络诈骗等问题",
        "color": "#7c3aed",
    },
    "procedure": {
        "label": "程序与救济",
        "dir": "06_procedure",
        "desc": "民事诉讼法、行政复议、行政处罚、国家赔偿、仲裁、法律援助、信访",
        "tool": "检索起诉流程、诉讼时效、管辖、上诉、行政复议、仲裁、法律援助等问题",
        "color": "#0e7490",
    },
}


def collection_name(domain: str) -> str:
    """领域 -> Milvus 集合名。统一前缀，便于在 Milvus 里一眼区分业务集合。"""
    return f"law_{domain}"


# 用户上传文档单独一个集合，和内置法律库物理隔离，删的时候不会误伤
UPLOAD_COLLECTION = "law_upload"

# 检索默认值提升为模块级常量，业务代码 from config import DEFAULT_TOP_K 即可，
# 不用每次写 settings.DEFAULT_TOP_K
DEFAULT_TOP_K = settings.DEFAULT_TOP_K
DEFAULT_RERANK_N = settings.DEFAULT_RERANK_N
USE_BM25 = settings.USE_BM25
BM25_TOP_K = settings.BM25_TOP_K
RRF_K = settings.RRF_K

# ---------------------------------------------------------------- 目录预热
for _path in (settings.STORAGE_DIR, settings.KNOWLEDGE_DIR,
              settings.UPLOAD_DIR, settings.MILVUS_DIR):
    Path(_path).mkdir(parents=True, exist_ok=True)
