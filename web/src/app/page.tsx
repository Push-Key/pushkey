import Navbar from "@/components/Navbar"
import Hero from "@/components/Hero"
import TrustBar from "@/components/TrustBar"
import HowItWorks from "@/components/HowItWorks"
import Features from "@/components/Features"
import ComparisonTable from "@/components/ComparisonTable"
import SecuritySection from "@/components/SecuritySection"
import Pricing from "@/components/Pricing"
import Testimonials from "@/components/Testimonials"
import FAQ from "@/components/FAQ"
import CTA from "@/components/CTA"
import Footer from "@/components/Footer"

export default function HomePage() {
  return (
    <main className="relative overflow-x-hidden">
      <Navbar />
      <Hero />
      <TrustBar />
      <HowItWorks />
      <Features />
      <ComparisonTable />
      <SecuritySection />
      <Pricing />
      <Testimonials />
      <FAQ />
      <CTA />
      <Footer />
    </main>
  )
}
