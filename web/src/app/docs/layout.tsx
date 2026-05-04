import { DocsLayout } from "fumadocs-ui/layouts/docs"
import { source } from "@/lib/source"
import type { ReactNode } from "react"
import "fumadocs-ui/style.css"

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <DocsLayout
      tree={source.pageTree}
      nav={{
        title: (
          <div className="flex items-center gap-2">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/logo.png" alt="PushKey" width={24} height={24} style={{ borderRadius: 6 }} />
            <span style={{ fontWeight: 700 }}>PushKey</span>
          </div>
        ),
      }}
    >
      {children}
    </DocsLayout>
  )
}
