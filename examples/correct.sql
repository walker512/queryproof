-- Revenue from sales belonging to any labeled customer, without multiplying rows.
SELECT SUM(CAST(s.amount AS REAL)) AS reported_revenue
FROM sales s
WHERE EXISTS (SELECT 1 FROM labels l WHERE l.customer = s.customer);
