from pyspark.sql import functions as F

frame_1 = spark.table("source").alias("source")
frame_1 = frame_1.select(F.expr("CAST(id AS STRING) AS id"))
df = frame_1
