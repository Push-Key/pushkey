import Link from "next/link"


export default function NotFound() {
  return (
    <main className="min-h-screen bg-[#060B14] text-white flex items-center justify-center px-6">
      <div className="max-w-md text-center">
        <p className="text-xs uppercase tracking-[0.2em] text-[#00DC82] mb-3">404</p>
        <h1 className="text-3xl font-bold mb-3">Page not found</h1>
        <p className="text-sm text-[#94A3B8] mb-6">
          This PushKey page is not available in the alpha launch surface.
        </p>
        <Link
          href="/"
          className="inline-flex items-center justify-center rounded-lg bg-[#00DC82] px-4 py-2 text-sm font-semibold text-[#060B14]"
        >
          Back to PushKey
        </Link>
      </div>
    </main>
  )
}
