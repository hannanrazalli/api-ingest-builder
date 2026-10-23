from pyspark.sql import functions as F

frame_1 = spark.table("source").alias("source")
frame_1 = frame_1.groupBy().agg(F.expr("MIN(amount) AS lo"), F.expr("MAX(amount) AS hi"))
frame_1 = frame_1.select(*["lo", "hi"])
df = frame_1
