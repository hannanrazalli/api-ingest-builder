from pyspark.sql import functions as F

frame_1 = spark.table("source").alias("source")
frame_1 = frame_1.select(
    F.expr("id"),
    F.expr(("SUM(amount) OVER (ORDER BY id range BETWEEN 1 preceding AND 1 following) AS total")),
)
df = frame_1
