{{/* Common labels for every object of the release. */}}
{{- define "hb.labels" -}}
app.kubernetes.io/part-of: hirebuddha
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
hirebuddha.com/env: {{ .Values.global.env | quote }}
{{- end -}}

{{/* Selector labels of one component: (dict "root" $ "component" "api") */}}
{{- define "hb.selectorLabels" -}}
app.kubernetes.io/name: {{ .component }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
{{- end -}}

{{/* An image reference: (dict "root" $ "image" "api") */}}
{{- define "hb.image" -}}
{{- $repo := index .root.Values.images .image -}}
{{- with .root.Values.global.imageRegistry -}}{{ . }}/{{- end -}}{{ $repo }}:{{ .root.Values.global.imageTag }}
{{- end -}}

{{/* Pod-level settings shared by the backend pods. */}}
{{- define "hb.podSpecCommon" -}}
{{- with .Values.global.imagePullSecrets }}
imagePullSecrets:
  {{- toYaml . | nindent 2 }}
{{- end }}
securityContext:
  {{- toYaml .Values.securityContext | nindent 2 }}
{{- with .Values.nodeSelector }}
nodeSelector:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.tolerations }}
tolerations:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- end -}}

{{/* Pod labels for backend pods: selector + podLabels. */}}
{{- define "hb.podLabels" -}}
{{ include "hb.selectorLabels" . }}
{{- with .root.Values.podLabels }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{/* Settings for a backend container: ConfigMap, optional Secret, CSI mount dir. */}}
{{- define "hb.backendEnv" -}}
envFrom:
  - configMapRef:
      name: {{ .Release.Name }}-config
  {{- with .Values.secrets.existingSecret }}
  - secretRef:
      name: {{ . }}
  {{- end }}
env:
{{- include "hb.commonEnv" . }}
{{- end -}}

{{/* The same settings with the config inlined: for the pre-install migration
     hook, which runs before the release's ConfigMap exists. */}}
{{- define "hb.backendEnvInline" -}}
{{- with .Values.secrets.existingSecret }}
envFrom:
  - secretRef:
      name: {{ . }}
{{- end }}
env:
  {{- range $key, $value := .Values.config }}
  {{- if ne (toString $value) "" }}
  - name: {{ $key }}
    value: {{ $value | toString | quote }}
  {{- end }}
  {{- end }}
{{- include "hb.commonEnv" . }}
{{- end -}}

{{- define "hb.commonEnv" -}}
  {{- if .Values.secrets.csi.enabled }}
  - name: SETTINGS_SECRETS_DIR
    value: {{ .Values.secrets.csi.mountPath | quote }}
  {{- end }}
  - name: INSTANCE_ID
    valueFrom:
      fieldRef:
        fieldPath: metadata.name
  {{- if .Values.googleFederation.enabled }}
  - name: GOOGLE_WIF_CREDENTIAL_FILE
    value: /var/run/secrets/google/credential-config.json
  {{- end }}
  {{- with .Values.extraEnv }}
  {{- toYaml . | nindent 2 }}
  {{- end }}
{{- end -}}

{{/* Writable paths of a read-only container, and the CSI secrets mount. */}}
{{- define "hb.backendVolumeMounts" -}}
volumeMounts:
  - name: tmp
    mountPath: /tmp
  - name: var
    mountPath: /app/var
  # Local-disk storage and the legacy static mounts (local/onprem profiles);
  # unused with Blob storage.
  - name: artifact
    mountPath: /app/artifact
  - name: uploads
    mountPath: /app/uploads
  {{- if .Values.secrets.csi.enabled }}
  - name: secrets-store
    mountPath: {{ .Values.secrets.csi.mountPath | quote }}
    readOnly: true
  {{- end }}
  {{- if .Values.googleFederation.enabled }}
  - name: google-federation
    mountPath: /var/run/secrets/google
    readOnly: true
  {{- end }}
{{- end -}}

{{/* (dict "root" $ "identity" "api"|"worker"|"migrations"): the CSI mount reads
     Key Vault as that workload's own identity. */}}
{{- define "hb.backendVolumes" -}}
volumes:
  - name: tmp
    emptyDir:
      sizeLimit: 2Gi
  - name: var
    emptyDir:
      sizeLimit: 10Gi
  - name: artifact
    emptyDir:
      sizeLimit: 10Gi
  - name: uploads
    emptyDir:
      sizeLimit: 1Gi
  {{- if .root.Values.secrets.csi.enabled }}
  - name: secrets-store
    csi:
      driver: {{ .root.Values.secrets.csi.driver }}
      readOnly: true
      volumeAttributes:
        secretProviderClass: {{ .root.Release.Name }}-secrets-{{ .identity }}
  {{- end }}
  {{- if .root.Values.googleFederation.enabled }}
  # Google workload identity federation (WS1 1.5): the pod's own service-account
  # token, for Google's audience, beside the external_account configuration
  # that GOOGLE_WIF_CREDENTIAL_FILE names. No Google key file anywhere.
  - name: google-federation
    projected:
      sources:
        - serviceAccountToken:
            audience: {{ required "googleFederation.audience is required" .root.Values.googleFederation.audience | quote }}
            expirationSeconds: 3600
            path: token
        - configMap:
            name: {{ .root.Release.Name }}-google-federation
            items:
              - key: credential-config.json
                path: credential-config.json
  {{- end }}
{{- end -}}


{{/* DATABASE_URL for one workload when the chart builds it: (dict "root" $ "user" "api").
     On Azure each workload signs in as its own Entra principal (DB_AUTH=entra_token). */}}
{{- define "hb.databaseUrlEnv" -}}
{{- $db := .root.Values.database -}}
{{- if $db.url }}
- name: DATABASE_URL
  value: {{ replace "{user}" (index $db.users .user) $db.url | quote }}
{{- end }}
{{- end -}}
