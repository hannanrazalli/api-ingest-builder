from pyspark.sql import functions as F

frame_1 = spark.table("source").alias("source")
frame_1 = frame_1.groupBy(F.expr("category")).agg(F.expr("SUM(amount) AS total"))
frame_1 = frame_1.filter(F.expr("total > 20"))
frame_1 = frame_1.select(*["category", "total"])
df = frame_1
