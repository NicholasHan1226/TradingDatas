import { useState, type ReactNode } from 'react'
import { Activity, BarChart3, Database, KeyRound, SearchCode } from 'lucide-react'
import type { ApiClient } from '../../lib/api'
import WorkspaceShell, { type WorkspaceNavItem } from '../../components/WorkspaceShell'
import TokensView from './TokensView'
import UsageView from './UsageView'
import CollectionView from './CollectionView'
import HealthView from './HealthView'
import DataView from './DataView'

type SectionKey = 'tokens' | 'usage' | 'collection' | 'health' | 'browser'

const NAV: WorkspaceNavItem<SectionKey>[] = [
  { key: 'tokens', label: '客户与密钥', description: '账户、套餐与授权', group: 'Access', icon: KeyRound, accent: 'blue' },
  { key: 'usage', label: '用量与容量', description: '请求趋势与配额', group: 'Access', icon: BarChart3, accent: 'violet' },
  { key: 'collection', label: '数据运行面', description: '采集与新鲜度', group: 'Data', icon: Database, accent: 'cyan' },
  { key: 'health', label: '异常中心', description: '风险与诊断', group: 'Data', icon: Activity, accent: 'orange' },
  { key: 'browser', label: '数据浏览器', description: '目录与样本验证', group: 'Data', icon: SearchCode, accent: 'blue' },
]

export default function AdminApp({
  client,
  onLogout,
  onViewCustomer,
}: {
  client: ApiClient
  onLogout: () => void
  onViewCustomer: () => void
}) {
  const [section, setSection] = useState<SectionKey>('tokens')

  const views: Record<SectionKey, ReactNode> = {
    tokens: <TokensView client={client} />,
    usage: <UsageView client={client} />,
    collection: <CollectionView client={client} />,
    health: <HealthView client={client} />,
    browser: <DataView client={client} />,
  }

  return (
    <WorkspaceShell
      workspace="admin"
      workspaceLabel="管理员工作台"
      items={NAV}
      active={section}
      onSelect={setSection}
      onSwitch={onViewCustomer}
      switchLabel="预览客户门户"
      onLogout={onLogout}
    >
      {views[section]}
    </WorkspaceShell>
  )
}
