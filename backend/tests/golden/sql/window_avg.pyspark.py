from pyspark.sql import functions as F

frame_1 = spark.table("source").alias("source")
frame_1 = frame_1.select(
    F.expr("id"),
    F.expr(
        (
            "AVG(amount) OVER (PARTITION BY category ORDER BY id row"
            "s BETWEEN UNBOUNDED preceding AND CURRENT ROW) AS rolli"
            "ng"
        )
    ),
)
df = frame_1
