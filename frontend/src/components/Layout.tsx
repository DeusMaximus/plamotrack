import { NavLink, Outlet } from "react-router-dom";

const NAV = [
  { to: "/board", label: "Board", icon: "📋" },
  { to: "/kits", label: "Kits", icon: "🤖" },
  { to: "/orders", label: "Orders", icon: "📦" },
  { to: "/inventory", label: "Inventory", icon: "🛠️" },
  { to: "/retailers", label: "Retailers", icon: "🏪" },
  { to: "/data", label: "Data", icon: "💾" },
];

export function Layout() {
  return (
    <div className="flex min-h-screen">
      <aside className="w-52 shrink-0 border-r border-zinc-200 bg-white">
        <div className="px-4 py-5">
          <h1 className="text-xl font-bold tracking-tight text-indigo-600">plamotrack</h1>
          <p className="mt-0.5 text-[11px] leading-tight text-zinc-400">
            pre-order → panel-lined masterpiece
          </p>
        </div>
        <nav className="space-y-0.5 px-2">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium ${
                  isActive
                    ? "bg-indigo-50 text-indigo-700"
                    : "text-zinc-600 hover:bg-zinc-50 hover:text-zinc-900"
                }`
              }
            >
              <span aria-hidden>{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="min-w-0 flex-1 p-6">
        <Outlet />
      </main>
    </div>
  );
}
