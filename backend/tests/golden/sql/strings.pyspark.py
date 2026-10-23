from pyspark.sql import functions as F

frame_1 = spark.table("source").alias("source")
frame_1 = frame_1.filter(F.expr("category LIKE 'a%'"))
frame_1 = frame_1.select(F.expr("id"), F.expr("UPPER(category) AS category"))
df = frame_1
