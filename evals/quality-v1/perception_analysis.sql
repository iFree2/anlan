-- Only explicitly selected synthetic review IDs; caller starts a READ ONLY transaction.
SELECT r.result->>'status' AS result_status,
       r.result->'report'->>'stop_reason' AS stop_reason,
       a.status AS attempt_status,
       a.work_package,
       r.feedback->>'decision' AS feedback_decision,
       count(*) AS reviews,
       sum((a.usage->>'total_tokens')::bigint) AS known_total_tokens
FROM anlan_v2.perception_reviews AS r
LEFT JOIN anlan_v2.model_budget_attempts AS a
  ON a.run_id = r.document->>'run_id' AND a.authorization_id = %s
WHERE r.tenant_id = %s AND r.user_id = %s AND r.review_id = ANY(%s)
GROUP BY result_status, stop_reason, a.status, a.work_package, feedback_decision
ORDER BY stop_reason;
