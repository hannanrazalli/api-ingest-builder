from pyspark.sql import functions as F

frame_1 = spark.table("source").alias("source")
frame_1 = frame_1.select(F.expr("id"))
frame_1 = frame_1.orderBy(F.expr("id").asc_nulls_first())
frame_1 = frame_1.limit(2)
df = frame_1
