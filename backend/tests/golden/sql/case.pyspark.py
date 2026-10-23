from pyspark.sql import functions as F

frame_1 = spark.table("source").alias("source")
frame_1 = frame_1.select(
    F.expr("id"), F.expr("CASE WHEN amount > 10 THEN 'big' ELSE 'small' END AS size")
)
df = frame_1
