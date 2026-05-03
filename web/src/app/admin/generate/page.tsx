import { redirect } from "next/navigation"

export default function GeneratePage() {
  redirect("/admin/licenses?generate=1")
}
