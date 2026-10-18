{{- define "hbb.labels" -}}
app.kubernetes.io/part-of: hirebuddha
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
hirebuddha.com/env: {{ .Values.env | quote }}
{{- end -}}
