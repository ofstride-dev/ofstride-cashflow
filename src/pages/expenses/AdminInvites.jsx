import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useCashflowAuth } from "../../context/CashflowAuthContext";

function AdminInvites() {
  const { invites, inviteMember, profile } = useCashflowAuth();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("employee");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  const sortedInvites = useMemo(() => [...(invites || [])], [invites]);

  const handleSubmit = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    setInfo("");
    try {
      const invite = await inviteMember(email.trim(), role);
      setInfo(`${invite.role === "admin" ? "Admin" : "Employee"} invite sent to ${invite.email}.`);
      setEmail("");
    } catch (nextError) {
      setError(nextError?.message || "Invite could not be sent.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-primary">Admin Invites</h1>
          <p className="text-sm text-muted mt-1">
            Invite another admin into {profile?.company_name || "your workspace"}.
          </p>
        </div>
        <Link to="/cashflow/dashboard" className="btn-ui btn-ui-sm btn-ui-neutral">
          Back to dashboard
        </Link>
      </div>

      <div className="bg-white rounded-2xl p-6 shadow-sm">
        {error && (
          <div className="rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800 mb-4">
            {error}
          </div>
        )}
        {info && (
          <div className="rounded-xl border border-emerald-300 bg-emerald-50 px-4 py-3 text-sm text-emerald-800 mb-4">
            {info}
          </div>
        )}
        <form className="flex flex-col sm:flex-row gap-3" onSubmit={handleSubmit}>
          <select
            value={role}
            onChange={(event) => setRole(event.target.value)}
            className="px-4 py-3 rounded-xl border border-slate-200 focus:border-secondary focus:ring-2 focus:ring-secondary/20 outline-none"
          >
            <option value="employee">Employee</option>
            <option value="admin">Admin</option>
          </select>
          <input
            type="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="name@company.com"
            className="flex-1 px-4 py-3 rounded-xl border border-slate-200 focus:border-secondary focus:ring-2 focus:ring-secondary/20 outline-none"
          />
          <button type="submit" disabled={submitting} className="btn-ui btn-ui-primary">
            {submitting ? "Sending..." : `Send ${role === "admin" ? "Admin" : "Employee"} Invite`}
          </button>
        </form>
      </div>

      <div className="bg-white rounded-2xl shadow-sm divide-y divide-slate-100">
        {sortedInvites.length === 0 && (
          <div className="p-6 text-sm text-muted">No invites yet.</div>
        )}
        {sortedInvites.map((invite) => (
          <div key={invite.id || invite.invite_token} className="p-6 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div>
              <p className="font-medium text-primary">{invite.email}</p>
              <p className="text-sm text-muted">
                {invite.role} · {invite.status} · expires {String(invite.expires_at || "").slice(0, 10) || "soon"}
              </p>
            </div>
            <div className="text-xs text-slate-500 break-all">
              token: {invite.invite_token}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default AdminInvites;
