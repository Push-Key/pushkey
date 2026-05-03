"use client"
import { useState, useEffect } from "react"
import { Menu, X } from "lucide-react"
import Image from "next/image"

export default function Navbar() {
  const [scrolled, setScrolled] = useState(false)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    const handler = () => setScrolled(window.scrollY > 20)
    window.addEventListener("scroll", handler)
    return () => window.removeEventListener("scroll", handler)
  }, [])

  return (
    <nav
      className="fixed top-0 left-0 right-0 z-50 transition-all duration-300"
      style={{
        background: scrolled ? "rgba(6,11,20,0.95)" : "transparent",
        backdropFilter: scrolled ? "blur(12px)" : "none",
        borderBottom: scrolled ? "1px solid rgba(255,255,255,0.08)" : "none",
      }}
    >
      <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Image src="/logo.png" alt="PushKey" width={32} height={32} className="rounded-lg" />
          <span className="font-bold text-lg tracking-tight" style={{ fontFamily: "var(--font-geist-sans, system-ui)" }}>PushKey</span>
        </div>

        {/* Desktop nav */}
        <div className="hidden md:flex items-center gap-8">
          {["Features", "Security", "Pricing", "FAQ"].map(item => (
            <a key={item} href={`#${item.toLowerCase()}`} className="text-sm transition-colors" style={{ color: "#94A3B8" }}
              onMouseEnter={e => (e.currentTarget.style.color = "#F8FAFC")}
              onMouseLeave={e => (e.currentTarget.style.color = "#94A3B8")}>
              {item}
            </a>
          ))}
        </div>

        <div className="hidden md:flex items-center gap-3">
          <a href="#pricing" className="text-sm px-4 py-2 rounded-lg transition-colors" style={{ color: "#94A3B8" }}
            onMouseEnter={e => (e.currentTarget.style.color = "#F8FAFC")}
            onMouseLeave={e => (e.currentTarget.style.color = "#94A3B8")}>
            Sign in
          </a>
          <a href="#pricing" className="text-sm px-4 py-2 rounded-lg font-medium transition-all"
            style={{ background: "#00DC82", color: "#060B14" }}
            onMouseEnter={e => (e.currentTarget.style.opacity = "0.9")}
            onMouseLeave={e => (e.currentTarget.style.opacity = "1")}>
            Download Free
          </a>
        </div>

        {/* Mobile menu button */}
        <button className="md:hidden" onClick={() => setOpen(!open)} style={{ color: "#94A3B8" }}>
          {open ? <X size={20} /> : <Menu size={20} />}
        </button>
      </div>

      {/* Mobile menu */}
      {open && (
        <div className="md:hidden px-6 pb-4 space-y-3" style={{ background: "rgba(6,11,20,0.98)", borderBottom: "1px solid rgba(255,255,255,0.08)" }}>
          {["Features", "Security", "Pricing", "FAQ"].map(item => (
            <a key={item} href={`#${item.toLowerCase()}`} onClick={() => setOpen(false)}
              className="block text-sm py-2" style={{ color: "#94A3B8" }}>{item}</a>
          ))}
          <a href="#pricing" className="block text-sm px-4 py-2 rounded-lg font-medium text-center mt-2"
            style={{ background: "#00DC82", color: "#060B14" }}>
            Download Free
          </a>
        </div>
      )}
    </nav>
  )
}
