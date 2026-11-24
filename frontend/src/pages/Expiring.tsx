import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api, type ChartSpec, type PullLine } from "../api";
import ChartView from "../components/ChartView";
import ExpiringLots from "../components/ExpiringLots";
import PullListForm from "../components/PullListForm";
import PageHeader from "../components/ui/PageHeader";
import Segmented from "../components/ui/Segmented";

type Tab = "lots" | "pull";

export default function Expiring() {
  const [params, setParams] = useSearchParams();
  const tab: Tab = params.get("tab") === "pull" ? "pull" : "lots";
  const setTab = (t: Tab) => setParams(t === "pull" ? { tab: "pull" } : {}, { replace: true });
  const chart = useQuery({ queryKey: ["chart-expiry"], queryFn: () => api<ChartSpec>(`/charts?metric=expiry_risk`) });
  const pull = useQuery({ queryKey: ["pull-list"], queryFn: () => api<{ closing_hour: number; lots: PullLine[] }>("/shelf/pull-list") });

  return (
    <>
      <PageHeader
        title="Hàng cận date"
        desc="Dự kiến hủy tính bằng mô phỏng bán FEFO theo dự báo nhu cầu. Phương án xếp theo tiền thu hồi kỳ vọng."
      />
      <div className="row mb-4">
        <Segmented<Tab> label="Phần việc" value={tab} onChange={setTab} options={[
          { value: "lots", label: "Lô cận date" },
          { value: "pull", label: "Rút kệ", count: pull.data?.lots.length },
        ]} />
      </div>
      {tab === "pull" ? (
        <PullListForm lines={pull.data?.lots ?? []} title={`Rút kệ cuối ngày (sau ${pull.data?.closing_hour ?? 22}h)`}
          note="Bắt buộc: gỡ hết hàng của các lô đã qua ngày bán cuối và ghi số thực gỡ. Không cần chờ duyệt; Store Manager chỉ duyệt bút toán ghi hủy." />
      ) : (
        <>
          <ExpiringLots initialDays={7} />
          {chart.data && (
            <div className="mt-3">
              <ChartView spec={chart.data} height={180} />
            </div>
          )}
        </>
      )}
    </>
  );
}
