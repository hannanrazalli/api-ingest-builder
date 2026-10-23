from pyspark.sql import functions as F

frame_2 = spark.table("source").alias("source")
frame_2 = frame_2.filter(F.expr("id < 3"))
frame_2 = frame_2.select(F.expr("id"))
frame_3 = spark.table("source").alias("source")
frame_3 = frame_3.filter(F.expr("id > 1"))
frame_3 = frame_3.select(F.expr("id"))
frame_1 = frame_2.union(frame_3)
df = frame_1
