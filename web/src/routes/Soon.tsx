import { Hammer } from 'lucide-react'
import { EmptyState } from '../ui/Card'

export default function Soon({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="mx-auto max-w-3xl p-10">
      <h1 className="mb-4 text-xl font-semibold tracking-tight">{title}</h1>
      <EmptyState icon={<Hammer size={28} />} title="Being rebuilt" hint={hint} />
    </div>
  )
}
