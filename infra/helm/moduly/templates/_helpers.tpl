{{/*
Expand the name of the chart.
*/}}
{{- define "moduly.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Reject an ingress-backed production gateway that cannot recover the client
network. Direct gateway deployments may intentionally keep the list empty.
*/}}
{{- define "moduly.validateLoginTrustedProxy" -}}
{{- $nodeEnv := lower (.Values.gateway.env.NODE_ENV | default "production") -}}
{{- if and .Values.gateway.enabled .Values.ingress.enabled (eq $nodeEnv "production") (empty .Values.gateway.env.AUTH_LOGIN_TRUSTED_PROXY_CIDRS) -}}
{{- fail "gateway.env.AUTH_LOGIN_TRUSTED_PROXY_CIDRS is required for an ingress-backed production gateway" -}}
{{- end -}}
{{- end -}}

{{/*
Normalize and validate the chart-wide document storage contract. CLOUD must
never render without both coordinates; provider credentials remain external.
*/}}
{{- define "moduly.storageType" -}}
{{- upper (trim (default "LOCAL" .Values.storage.type)) -}}
{{- end -}}

{{- define "moduly.validateStorage" -}}
{{- $legacyGatewayStorage := or (hasKey .Values.gateway.env "STORAGE_TYPE") (hasKey .Values.gateway.env "S3_BUCKET_NAME") (hasKey .Values.gateway.env "AWS_REGION") -}}
{{- $legacyWorkerStorage := or (hasKey .Values.worker.env "S3_BUCKET_NAME") (hasKey .Values.worker.env "AWS_REGION") -}}
{{- if or $legacyGatewayStorage $legacyWorkerStorage -}}
{{- fail "legacy component storage keys are unsupported; use the root storage block" -}}
{{- end -}}
{{- $storageType := include "moduly.storageType" . -}}
{{- if not (has $storageType (list "LOCAL" "CLOUD")) -}}
{{- fail "storage.type must be LOCAL or CLOUD" -}}
{{- end -}}
{{- if eq $storageType "CLOUD" -}}
{{- if empty (trim (default "" .Values.storage.bucketName)) -}}
{{- fail "storage.bucketName is required when storage.type is CLOUD" -}}
{{- end -}}
{{- if empty (trim (default "" .Values.storage.region)) -}}
{{- fail "storage.region is required when storage.type is CLOUD" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "moduly.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "moduly.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "moduly.labels" -}}
helm.sh/chart: {{ include "moduly.chart" . }}
{{ include "moduly.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "moduly.selectorLabels" -}}
app.kubernetes.io/name: {{ include "moduly.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
  Schedule dispatch is intentionally explicit in both Gateway and Worker pods.
  Keeping the values in one chart-level block prevents the two admission
  boundaries from silently using different modes or deadlines.
*/}}
{{- define "moduly.scheduleDispatchFingerprint" -}}
{{- printf "v1|%v|%v|%v|%v|%v|%v|%v|%v|%v|%v|%v|%v|%v|%v" .Values.scheduleDispatch.mode .Values.scheduleDispatch.pollSeconds .Values.scheduleDispatch.occurrenceBatchSize .Values.scheduleDispatch.dispatchBatchSize .Values.scheduleDispatch.recoveryBatchSize .Values.scheduleDispatch.cleanupBatchSize .Values.scheduleDispatch.leaseSeconds .Values.scheduleDispatch.deliveryTimeoutSeconds .Values.scheduleDispatch.executionDeadlineSeconds .Values.scheduleDispatch.workflowRunVisibilityTimeoutSeconds .Values.scheduleDispatch.maxAttempts .Values.scheduleDispatch.retryBaseSeconds .Values.scheduleDispatch.retentionDays .Values.scheduleDispatch.deadLetterRetentionDays -}}
{{- end }}

{{- define "moduly.validateScheduleDispatchMode" -}}
{{- if ne .Values.scheduleDispatch.mode "disabled" -}}
{{- fail "non-disabled schedule dispatch is unsupported by the current provider-neutral deployment surface" -}}
{{- end -}}
{{- end }}

{{- define "moduly.scheduleDispatchEnv" -}}
- name: SCHEDULE_DISPATCH_MODE
  value: {{ .Values.scheduleDispatch.mode | quote }}
- name: SCHEDULE_DISPATCH_MODE_FINGERPRINT
  valueFrom:
    fieldRef:
      fieldPath: metadata.annotations['nodease.io/schedule-dispatch-fingerprint']
- name: SCHEDULE_DISPATCH_POLL_SECONDS
  value: {{ .Values.scheduleDispatch.pollSeconds | quote }}
- name: SCHEDULE_OCCURRENCE_BATCH_SIZE
  value: {{ .Values.scheduleDispatch.occurrenceBatchSize | quote }}
- name: SCHEDULE_DISPATCH_BATCH_SIZE
  value: {{ .Values.scheduleDispatch.dispatchBatchSize | quote }}
- name: SCHEDULE_RECOVERY_BATCH_SIZE
  value: {{ .Values.scheduleDispatch.recoveryBatchSize | quote }}
- name: SCHEDULE_CLEANUP_BATCH_SIZE
  value: {{ .Values.scheduleDispatch.cleanupBatchSize | quote }}
- name: SCHEDULE_DISPATCH_LEASE_SECONDS
  value: {{ .Values.scheduleDispatch.leaseSeconds | quote }}
- name: SCHEDULE_ENQUEUED_DELIVERY_TIMEOUT_SECONDS
  value: {{ .Values.scheduleDispatch.deliveryTimeoutSeconds | quote }}
- name: SCHEDULE_EXECUTION_DEADLINE_SECONDS
  value: {{ .Values.scheduleDispatch.executionDeadlineSeconds | quote }}
- name: SCHEDULE_WORKFLOW_RUN_VISIBILITY_TIMEOUT_SECONDS
  value: {{ .Values.scheduleDispatch.workflowRunVisibilityTimeoutSeconds | quote }}
- name: SCHEDULE_DISPATCH_MAX_ATTEMPTS
  value: {{ .Values.scheduleDispatch.maxAttempts | quote }}
- name: SCHEDULE_DISPATCH_RETRY_BASE_SECONDS
  value: {{ .Values.scheduleDispatch.retryBaseSeconds | quote }}
- name: SCHEDULE_DISPATCH_RETENTION_DAYS
  value: {{ .Values.scheduleDispatch.retentionDays | quote }}
- name: SCHEDULE_DISPATCH_DEAD_LETTER_RETENTION_DAYS
  value: {{ .Values.scheduleDispatch.deadLetterRetentionDays | quote }}
{{- end }}

{{/*
Component-specific labels
Usage: {{ include "moduly.componentLabels" (dict "component" "gateway" "context" .) }}
*/}}
{{- define "moduly.componentLabels" -}}
{{ include "moduly.labels" .context }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{/*
Component-specific selector labels
Usage: {{ include "moduly.componentSelectorLabels" (dict "component" "gateway" "context" .) }}
*/}}
{{- define "moduly.componentSelectorLabels" -}}
{{ include "moduly.selectorLabels" .context }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "moduly.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "moduly.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Get PostgreSQL host
*/}}
{{- define "moduly.postgresql.host" -}}
{{- if .Values.postgresql.enabled }}
{{- printf "%s-postgresql" .Release.Name }}
{{- else }}
{{- required "External PostgreSQL host must be specified when postgresql.enabled is false" .Values.postgresql.externalHost }}
{{- end }}
{{- end }}

{{/*
Get Redis host
*/}}
{{- define "moduly.redis.host" -}}
{{- if .Values.redis.enabled }}
{{- printf "%s-redis-master" .Release.Name }}
{{- else }}
{{- required "External Redis host must be specified when redis.enabled is false" .Values.redis.externalHost }}
{{- end }}
{{- end }}

{{/*
Get the ConfigMap name
*/}}
{{- define "moduly.configMapName" -}}
{{- printf "%s-config" (include "moduly.fullname" .) }}
{{- end }}

{{/*
Get the Secret name
*/}}
{{- define "moduly.secretName" -}}
{{- printf "%s-secrets" (include "moduly.fullname" .) }}
{{- end }}

{{/*
Return the appropriate apiVersion for ingress
*/}}
{{- define "moduly.ingress.apiVersion" -}}
{{- if semverCompare ">=1.19-0" .Capabilities.KubeVersion.GitVersion }}
{{- print "networking.k8s.io/v1" }}
{{- else if semverCompare ">=1.14-0" .Capabilities.KubeVersion.GitVersion }}
{{- print "networking.k8s.io/v1beta1" }}
{{- else }}
{{- print "extensions/v1beta1" }}
{{- end }}
{{- end }}

{{/*
Return the appropriate apiVersion for NetworkPolicy
*/}}
{{- define "moduly.networkPolicy.apiVersion" -}}
{{- if semverCompare ">=1.7-0" .Capabilities.KubeVersion.GitVersion }}
{{- print "networking.k8s.io/v1" }}
{{- else }}
{{- print "extensions/v1beta1" }}
{{- end }}
{{- end }}
{{/* Shared claim used only when durable Knowledge workers consume LOCAL uploads. */}}
{{- define "moduly.knowledgeUploadClaimName" -}}
{{- default (printf "%s-knowledge-uploads" (include "moduly.fullname" .)) .Values.knowledgeWorker.localStorage.existingClaim -}}
{{- end -}}
