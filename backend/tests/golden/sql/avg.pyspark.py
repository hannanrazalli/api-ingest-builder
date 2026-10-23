from pyspark.sql import functions as F

frame_1 = spark.table("source").alias("source")
frame_1 = frame_1.groupBy(F.expr("category")).agg(F.expr("AVG(amount) AS mean"))
frame_1 = frame_1.select(*["category", "mean"])
df = frame_1
