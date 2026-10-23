from pyspark.sql import functions as F

frame_1 = spark.table("source").alias("source")
frame_1 = frame_1.select(F.expr("id"), F.expr("amount"))
frame_1 = frame_1.orderBy(F.expr("amount").desc_nulls_last(), F.expr("id").asc_nulls_first())
df = frame_1
