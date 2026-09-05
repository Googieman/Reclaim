-- Seed only the canonical tenant for the isolated T153 validation project.
-- This file is mounted by the T153 overlay and runs only on a fresh volume.
INSERT INTO public.tenants (tenant_id, display_name, status)
VALUES ('tenant-canonical-demo', 'Canonical T153 validation merchant', 'active')
ON CONFLICT (tenant_id) DO NOTHING;
