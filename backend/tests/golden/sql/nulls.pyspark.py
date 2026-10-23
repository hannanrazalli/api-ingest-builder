from pyspark.sql import functions as F

frame_1 = spark.table("source").alias("source")
frame_1 = frame_1.filter(F.expr("NOT amount IS NULL"))
frame_1 = frame_1.select(F.expr("id"), F.expr("COALESCE(amount, 0) AS value"))
df = frame_1
