import { Link } from "react-router-dom";
import { ArrowLeft, Crosshair } from "lucide-react";
import { EmptyState } from "../components/ui/EmptyState";

export default function NotFound() {
  return (
    <div className="not-found">
      <EmptyState
        icon={<Crosshair size={26} />}
        title="404 / 没有这个作战区域"
        description="链接可能已经失效，或者 page 还未被部署。回到总览重新选择任务。"
        action={
          <Link className="btn btn--primary btn--sm" to="/">
            <ArrowLeft size={13} />
            返回总览
          </Link>
        }
      />
    </div>
  );
}
