from pyspark.sql import functions as F

frame_1 = spark.table("source").alias("source")
frame_1 = frame_1.select(
    F.expr("id"),
    F.expr(
        (
            "SUM(amount) OVER (PARTITION BY category ORDER BY id row"
            "s BETWEEN 1 preceding AND CURRENT ROW) AS rolling"
        )
    ),
)
df = frame_1
