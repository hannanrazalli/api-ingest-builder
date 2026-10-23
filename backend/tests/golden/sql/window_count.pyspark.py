from pyspark.sql import functions as F

frame_1 = spark.table("source").alias("source")
frame_1 = frame_1.select(F.expr("id"), F.expr("COUNT(*) OVER (PARTITION BY category) AS n"))
df = frame_1
