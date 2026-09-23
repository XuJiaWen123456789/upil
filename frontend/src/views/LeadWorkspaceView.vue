<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { addLeadFollowUp, getLead, listLeads, revealLeadContact } from "@/api/leads";
import type {
  LeadContact,
  LeadDestination,
  LeadDetail,
  LeadFollowUpInput,
  LeadSummary,
} from "@/types/api";
import { formatApiDateTime } from "@/utils/datetime";

const destination = ref<LeadDestination>("advisor_queue");
const leads = ref<LeadSummary[]>([]);
const selected = ref<LeadDetail | null>(null);
const revealedContact = ref<LeadContact | null>(null);
const loading = ref(false);
const saving = ref(false);
const error = ref("");
const notice = ref("");
const action = ref<LeadFollowUpInput["action"]>("contact");
const result = ref<LeadFollowUpInput["result"]>("reached");
const note = ref("");
const nextFollowUpAt = ref("");

const actionLabels: Record<LeadFollowUpInput["action"], string> = {
  claim: "领取线索",
  contact: "联系家长",
  schedule_trial: "安排试听",
  confirm_enrollment: "确认报名",
  close: "关闭线索",
};
const resultOptions: Record<LeadFollowUpInput["action"], Array<{ value: LeadFollowUpInput["result"]; label: string }>> = {
  claim: [{ value: "claimed", label: "已领取" }],
  contact: [
    { value: "reached", label: "已联系" },
    { value: "unreachable", label: "暂未接通" },
    { value: "declined", label: "家长婉拒" },
  ],
  schedule_trial: [
    { value: "scheduled", label: "已安排" },
    { value: "cancelled", label: "已取消" },
  ],
  confirm_enrollment: [{ value: "enrolled", label: "已报名" }],
  close: [
    { value: "won", label: "成交关闭" },
    { value: "lost", label: "未成交关闭" },
  ],
};
const statusLabels: Record<string, string> = {
  open: "待跟进",
  awaiting_contact_consent: "等待家长授权",
  ready_for_followup: "可联系",
  contacted: "已联系",
  trial_scheduled: "已安排试听",
  enrolled: "已报名",
  closed_won: "已成交",
  closed_lost: "未成交",
};
const strengthLabels = { low: "低", medium: "中", high: "高" } as const;
const interestLabels = { trial: "试听", enrollment: "报名", unknown: "待确认" } as const;
const availableResults = computed(() => resultOptions[action.value]);
const isClosed = computed(() => selected.value?.status.startsWith("closed_") === true);

async function load(preferredLeadId?: string) {
  loading.value = true;
  error.value = "";
  notice.value = "";
  revealedContact.value = null;
  try {
    const page = await listLeads(destination.value);
    leads.value = page.items;
    const target = preferredLeadId
      ? page.items.find((item) => item.lead_id === preferredLeadId)
      : page.items[0];
    selected.value = target ? await getLead(target.lead_id) : null;
  } catch (cause) {
    leads.value = [];
    selected.value = null;
    error.value = cause instanceof Error ? cause.message : "销售线索暂时不可用";
  } finally {
    loading.value = false;
  }
}

async function chooseLead(leadId: string) {
  error.value = "";
  notice.value = "";
  revealedContact.value = null;
  try {
    selected.value = await getLead(leadId);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "线索详情暂时不可用";
  }
}

async function claim() {
  if (!selected.value) return;
  saving.value = true;
  error.value = "";
  try {
    await addLeadFollowUp(selected.value.lead_id, { action: "claim", result: "claimed" });
    await load(selected.value.lead_id);
    // load 会清理上一轮反馈，因此成功提示必须在刷新完成后写入。
    notice.value = "线索已领取，后续只有当前销售顾问老师可以查看和跟进。";
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "线索领取失败";
  } finally {
    saving.value = false;
  }
}

async function revealContact() {
  if (!selected.value?.assigned_to_me || !selected.value.contact_available) return;
  error.value = "";
  try {
    // 明文只保存在当前页面内存中；刷新、切换线索或切换队列都会清除。
    revealedContact.value = await revealLeadContact(selected.value.lead_id);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "联系方式暂时无法查看";
  }
}

function changeAction() {
  result.value = resultOptions[action.value][0].value;
}

async function submitFollowUp() {
  if (!selected.value?.assigned_to_me || isClosed.value) return;
  saving.value = true;
  error.value = "";
  notice.value = "";
  try {
    await addLeadFollowUp(selected.value.lead_id, {
      action: action.value,
      result: result.value,
      note: note.value.trim() || null,
      // datetime-local 没有时区；浏览器端转换为带时区 ISO，由后端统一解析。
      next_follow_up_at: nextFollowUpAt.value
        ? new Date(nextFollowUpAt.value).toISOString()
        : null,
    });
    note.value = "";
    nextFollowUpAt.value = "";
    await load(selected.value.lead_id);
    notice.value = "跟进记录已保存。";
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "跟进记录保存失败";
  } finally {
    saving.value = false;
  }
}

function switchDestination(next: LeadDestination) {
  destination.value = next;
  void load();
}

onMounted(() => void load());
</script>

<template>
  <div class="page-heading">
    <div><span class="eyebrow">SALES ADVISOR</span><h1>销售线索</h1><p>接收家长在对话中形成的试听与报名意向，并记录后续跟进。</p></div>
    <button class="button secondary" :disabled="loading" @click="load()">刷新</button>
  </div>

  <div class="lead-tabs" role="tablist" aria-label="线索分流">
    <button :class="{ active: destination === 'advisor_queue' }" role="tab" @click="switchDestination('advisor_queue')">顾问队列</button>
    <button :class="{ active: destination === 'lead_pool' }" role="tab" @click="switchDestination('lead_pool')">线索池</button>
  </div>
  <p v-if="error" class="alert">{{ error }}</p>
  <p v-if="notice" class="notice">{{ notice }}</p>

  <div class="lead-workspace">
    <section class="panel lead-list-panel">
      <div v-if="!leads.length && !loading" class="empty-state compact-empty"><h2>暂无可见线索</h2><p>新意向会由对话旁路自动归入相应范围。</p></div>
      <button
        v-for="lead in leads"
        :key="lead.lead_id"
        class="lead-list-item"
        :class="{ active: selected?.lead_id === lead.lead_id }"
        @click="chooseLead(lead.lead_id)"
      >
        <span class="lead-list-title"><strong>{{ lead.course_name }}</strong><i :class="['strength-dot', lead.strength]" /></span>
        <span>{{ interestLabels[lead.interest_type] }}意向 · {{ strengthLabels[lead.strength] }}强度</span>
        <small>{{ lead.learner_name || "学员待确认" }} · {{ statusLabels[lead.status] }}</small>
      </button>
    </section>

    <section v-if="selected" class="panel panel-pad lead-detail">
      <div class="lead-detail-head">
        <div><span class="eyebrow">LEAD DETAIL</span><h2>{{ selected.course_name }}</h2><p>{{ selected.learner_name || "学员待确认" }} · {{ interestLabels[selected.interest_type] }}意向</p></div>
        <span :class="['badge', selected.strength === 'high' ? 'warn' : '']">{{ strengthLabels[selected.strength] }}强度</span>
      </div>

      <div class="lead-facts">
        <div><span>当前状态</span><strong>{{ statusLabels[selected.status] }}</strong></div>
        <div><span>更新时间</span><strong>{{ formatApiDateTime(selected.updated_at) }}</strong></div>
        <div><span>联系方式</span><strong>{{ selected.contact_masked || "家长尚未授权" }}</strong></div>
      </div>

      <div class="lead-actions">
        <button v-if="!selected.assigned_to_me && !isClosed" class="button primary" :disabled="saving" @click="claim">领取线索</button>
        <button v-if="selected.assigned_to_me && selected.contact_available" class="button secondary" @click="revealContact">查看已授权联系方式</button>
        <span v-if="revealedContact" class="revealed-contact">{{ revealedContact.contact_type === 'phone' ? '手机号' : '邮箱' }}：{{ revealedContact.contact_value }}</span>
      </div>

      <form v-if="selected.assigned_to_me && !isClosed" class="follow-up-form" @submit.prevent="submitFollowUp">
        <h3>新增跟进</h3>
        <div class="form-grid">
          <label class="field"><span>动作</span><select v-model="action" @change="changeAction"><option v-for="(label, value) in actionLabels" :key="value" :value="value">{{ label }}</option></select></label>
          <label class="field"><span>结果</span><select v-model="result"><option v-for="item in availableResults" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>
          <label class="field"><span>下次跟进</span><input v-model="nextFollowUpAt" type="datetime-local" /></label>
          <label class="field span-2"><span>备注</span><textarea v-model="note" maxlength="500" placeholder="仅记录必要的跟进信息" /></label>
        </div>
        <button class="button primary" type="submit" :disabled="saving">{{ saving ? "保存中" : "保存跟进" }}</button>
      </form>

      <section class="follow-up-history">
        <h3>跟进历史</h3>
        <div v-if="!selected.follow_ups.length" class="metric-note">尚无跟进记录。</div>
        <article v-for="record in selected.follow_ups" :key="record.follow_up_id">
          <strong>{{ actionLabels[record.action as keyof typeof actionLabels] || record.action }} · {{ record.result }}</strong>
          <span>{{ formatApiDateTime(record.created_at) }}</span>
          <p v-if="record.note">{{ record.note }}</p>
        </article>
      </section>
    </section>
    <section v-else class="panel empty-state"><h2>选择一条线索</h2><p>详情区不会显示家长内部编号或意向模型原始输出。</p></section>
  </div>
</template>
