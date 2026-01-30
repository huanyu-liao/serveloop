import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 是否开启debug模式
DEBUG = True

# 读取数据库环境变量
username = os.environ.get("MYSQL_USERNAME", 'root')
password = os.environ.get("MYSQL_PASSWORD", 'pfBGb7gQ')
db_address = os.environ.get("MYSQL_ADDRESS", 'sh-cynosdbmysql-grp-p0hptv1u.sql.tencentcdb.com:20687')


