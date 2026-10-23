from pyspark.sql import functions as F

frame_1 = spark.table("source").alias("source")
frame_1 = frame_1.select(F.expr("category"))
frame_1 = frame_1.distinct()
df = frame_1
