from django.db import migrations

# The model already refuses to change or delete a record. This makes the database refuse
# too, so that a bug, a shell session or a hand-written query cannot quietly rewrite
# history either.
#
# Two changes stay possible, because both only ever remove personal data:
#   - clearing ``ip`` (addresses are forgotten after a while, see audit.services);
#   - clearing ``actor_id`` (what the foreign key does when an account is deleted).
# Nothing else about a record may change, and no record may be deleted.
CREATE = """
CREATE FUNCTION audit_auditlog_append_only() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE'
        AND (NEW.ip IS NULL OR NEW.ip IS NOT DISTINCT FROM OLD.ip)
        AND (NEW.actor_id IS NULL OR NEW.actor_id IS NOT DISTINCT FROM OLD.actor_id)
        AND ROW(NEW.id, NEW.actor_type, NEW.action, NEW.target_type, NEW.target_id,
                NEW.organization_id, NEW.community_id, NEW.metadata, NEW.request_id,
                NEW.created_at)
            IS NOT DISTINCT FROM
            ROW(OLD.id, OLD.actor_type, OLD.action, OLD.target_type, OLD.target_id,
                OLD.organization_id, OLD.community_id, OLD.metadata, OLD.request_id,
                OLD.created_at)
    THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'audit records are append-only'
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_auditlog_append_only
    BEFORE UPDATE OR DELETE ON audit_auditlog
    FOR EACH ROW EXECUTE FUNCTION audit_auditlog_append_only();
"""

DROP = """
DROP TRIGGER audit_auditlog_append_only ON audit_auditlog;
DROP FUNCTION audit_auditlog_append_only();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(CREATE, reverse_sql=DROP),
    ]
