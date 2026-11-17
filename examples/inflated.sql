-- Fictional pitfall: joining multiple labels duplicates sales amounts.
SELECT SUM(CAST(s.amount AS REAL)) AS reported_revenue
FROM sales s JOIN labels l ON s.customer = l.customer;
