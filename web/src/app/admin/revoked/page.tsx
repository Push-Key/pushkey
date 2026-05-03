import { redirect } from "next/navigation"

// Revoked view = licenses page pre-filtered; redirect with query when implemented
// For now redirect to licenses — user can click "Revoked" filter tab there
export default function RevokedPage() {
  redirect("/admin/licenses?tier=revoked")
}
