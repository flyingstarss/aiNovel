from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_base_url: str = ""
    llm_max_tokens: int = 8192
    # 流式输出时相邻 chunk 的最长等待秒数；0 表示不限制（长文生成时避免误判断流）
    llm_stream_chunk_timeout: float = 0
    # 网络抖动时的自动重试次数（连接失败、超时、502/503 等）
    llm_max_retries: int = 3
    llm_temp_editor: float = 0.8
    llm_temp_writer: float = 0.8
    llm_temp_reviewer: float = 0.2
    llm_temp_summary: float = 0.2
    llm_temp_humanizer: float = 0.35
    llm_concurrency: int = 3

    # MySQL
    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_user: str = "root"
    db_password: str = ""
    db_name: str = "novel_world"
    db_charset: str = "utf8mb4"
    # 连接池上限：避免每次查询都新建 TCP 连接
    db_pool_size: int = 5

    # 服务与目录
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    data_dir: str = "data"
    log_dir: str = "logs"

    @property
    def db_config(self) -> dict:
        return {
            "host": self.db_host,
            "port": self.db_port,
            "user": self.db_user,
            "password": self.db_password,
            "charset": self.db_charset,
        }

    def _absolute(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else BASE_DIR / path

    @property
    def data_path(self) -> Path:
        return self._absolute(self.data_dir)

    @property
    def log_path(self) -> Path:
        return self._absolute(self.log_dir)


settings = Settings()
