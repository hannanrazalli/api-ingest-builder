from pyspark.sql import functions as F

frame_1 = spark.table("source").alias("source")
frame_1 = frame_1.filter(F.expr("amount > 10"))
frame_1 = frame_1.select(F.expr("*"))
chosen = frame_1
frame_2 = chosen.alias("chosen")
frame_2 = frame_2.select(F.expr("id"))
df = frame_2
