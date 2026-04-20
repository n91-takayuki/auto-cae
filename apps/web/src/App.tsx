import { Toolbar } from "@/panels/Toolbar";
import { LeftTree } from "@/panels/LeftTree";
import { RightProps } from "@/panels/RightProps";
import { BottomLog } from "@/panels/BottomLog";
import { ResultLegend } from "@/panels/ResultLegend";
import { Toasts } from "@/panels/Toasts";
import { Viewer } from "@/scene/Viewer";

export default function App() {
  return (
    <div className="relative flex h-full w-full scene-bg noise overflow-hidden">
      <Viewer />

      <header className="pointer-events-none absolute inset-x-0 top-0 z-20 flex items-center justify-between p-4">
        <div className="pointer-events-auto flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent-gradient shadow-lg shadow-cyan-500/20">
            <span className="font-mono text-[10px] font-bold text-slate-950">CAE</span>
          </div>
          <div>
            <div className="text-sm font-semibold leading-tight">Auto-CAE</div>
            <div className="font-mono text-[10px] text-slate-400">linear static · mm-N-MPa</div>
          </div>
        </div>
        <Toolbar />
      </header>

      <aside className="absolute left-4 top-20 bottom-28 z-10 w-72">
        <LeftTree />
      </aside>

      <aside className="absolute right-4 top-20 bottom-28 z-10 w-80">
        <RightProps />
      </aside>

      <div className="pointer-events-none absolute bottom-28 left-1/2 z-10 -translate-x-1/2">
        <ResultLegend />
      </div>

      <footer className="absolute inset-x-4 bottom-4 z-10 h-20">
        <BottomLog />
      </footer>

      <Toasts />
    </div>
  );
}
