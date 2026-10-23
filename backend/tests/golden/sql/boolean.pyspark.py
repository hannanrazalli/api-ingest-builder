from pyspark.sql import functions as F

frame_1 = spark.table("source").alias("source")
frame_1 = frame_1.filter(F.expr("amount >= 10 AND id < 4"))
frame_1 = frame_1.select(F.expr("id"))
df = frame_1
