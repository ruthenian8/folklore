import pandas as pd
from sqlalchemy import create_engine
from folklore_app.settings import CONFIG_STR

con = create_engine(CONFIG_STR)
db = con.raw_connection()
cur = db.cursor()

df = pd.read_sql_query("SELECT id, old_id FROM texts WHERE year < 2019", con=con)
print(df.dtypes)
df2 = pd.read_csv("youtube.tsv", sep="\t", header=None, dtype="object")
df2.columns = ["old_id", "video"]
print(df2.dtypes)

df3 = df.merge(df2)[["id", "video"]]
print(df3)

cur.executemany("INSERT INTO t_video (id_text, video) VALUES (%s, %s)", df3.values.tolist())
db.commit()
