from pyspark.sql import functions as F

frame_1 = spark.table("source").alias("s")
frame_1 = frame_1.join(spark.table("other").alias("o"), F.expr("s.id = o.id"), "inner")
frame_1 = frame_1.select(F.expr("s.id"), F.expr("o.label"))
df = frame_1
