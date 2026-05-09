import { useCallback, useEffect, useState } from 'react'
import { type ContainerInfo, formatApiError, listContainers } from '../../api/client'

export function useContainerList(reportLoadError: (detail: string) => void) {
  const [rows, setRows] = useState<ContainerInfo[]>([])
  const [listLoading, setListLoading] = useState(true)

  const refresh = useCallback(async () => {
    setListLoading(true)
    try {
      const data = await listContainers()
      setRows(data)
    } catch (error) {
      reportLoadError(formatApiError(error))
    } finally {
      setListLoading(false)
    }
  }, [reportLoadError])

  useEffect(() => {
    void refresh()
  }, [refresh])

  return { rows, listLoading, refresh }
}
