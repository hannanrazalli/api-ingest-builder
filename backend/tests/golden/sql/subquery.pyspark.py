from pyspark.sql import functions as F

frame_2 = spark.table("source").alias("source")
frame_2 = frame_2.filter(F.expr("amount > 10"))
frame_2 = frame_2.select(F.expr("*"))
frame_1 = frame_2.alias("x")
frame_1 = frame_1.select(F.expr("id"))
df = frame_1
