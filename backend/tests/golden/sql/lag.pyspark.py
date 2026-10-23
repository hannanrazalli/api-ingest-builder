from pyspark.sql import functions as F

frame_1 = spark.table("source").alias("source")
frame_1 = frame_1.select(
    F.expr("id"), F.expr(("LAG(amount) OVER (PARTITION BY category ORDER BY id) AS previous"))
)
df = frame_1
