interface JsonViewerProps {
  data: unknown
}

export function JsonViewer({ data }: JsonViewerProps) {
  return (
    <pre className="max-h-64 overflow-auto rounded-lg bg-surface-tertiary p-4 text-xs text-content-primary">
      {JSON.stringify(data, null, 2)}
    </pre>
  )
}
