<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import FormModal from "@/components/crm/FormModal.vue";
import PickerField from "@/components/PickerField.vue";
import { apiError } from "@/components/crm/formError";
import { hrApi, type ChartNode, type Person, type Seat } from "@/api/hr";

/**
 * سمت: its title, and who holds it.
 *
 * The holder is picked from people who already exist. A new name can be
 * added from here, but it goes through the same duplicate check as the
 * people page — «ثبت شد» for «شیما نظام ابادی» when «شیما نظام آبادی» is
 * already there is how this module's whole problem started.
 */
const props = defineProps<{
  seat?: Seat | null;
  unit: ChartNode;
}>();
const emit = defineEmits<{ (e: "close"): void; (e: "saved"): void }>();

const inp =
  "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-slate-300";
const lbl = "text-xs text-slate-500 mb-1 block";

const people = ref<Person[]>([]);
const saving = ref(false);
const error = ref("");

const form = ref({
  title_fa: props.seat?.title ?? "",
  holder: props.seat?.holder ?? (null as number | null),
  is_head: props.seat?.is_head ?? false,
  on_sales_sheet: props.seat?.on_sales_sheet ?? true,
  note: props.seat?.note ?? "",
});

const holderOptions = computed(() => people.value.map((p) => ({
  value: p.id,
  label: p.full_name_fa,
  hint: p.positions.length
    ? p.positions.map((x) => `${x.title} (${x.unit})`).join("، ")
    : "بدون سمت",
})));

onMounted(async () => {
  people.value = await hrApi.people("active");
});

// ---- a new person, from here ----------------------------------------------
const addingPerson = ref(false);
const newName = ref("");
const duplicate = ref<Person | null>(null);

async function createPerson(force = false) {
  const name = newName.value.trim();
  if (!name) return;
  error.value = "";
  try {
    const person = await hrApi.savePerson({ full_name_fa: name, force });
    people.value = [...people.value, person];
    form.value.holder = person.id;
    addingPerson.value = false;
    duplicate.value = null;
    newName.value = "";
  } catch (e: any) {
    if (e?.response?.status === 409) {
      duplicate.value = e.response.data.duplicate;
    } else {
      error.value = apiError(e);
    }
  }
}

function useDuplicate() {
  const d = duplicate.value;
  if (!d) return;
  if (!d.is_active) {
    error.value = `«${d.full_name_fa}» در بایگانی است؛ اول از صفحه افراد او را بازگردانید.`;
    return;
  }
  form.value.holder = d.id;
  addingPerson.value = false;
  duplicate.value = null;
}

async function save() {
  if (!form.value.title_fa.trim()) {
    error.value = "عنوان سمت الزامی است.";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    await hrApi.savePosition({ ...form.value, unit: props.unit.id }, props.seat?.id);
    emit("saved");
  } catch (e) {
    error.value = apiError(e);
  } finally {
    saving.value = false;
  }
}

async function remove() {
  if (!props.seat) return;
  saving.value = true;
  try {
    await hrApi.removePosition(props.seat.id);
    emit("saved");
  } catch (e) {
    error.value = apiError(e);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <FormModal
    :title="seat ? 'ویرایش سمت' : 'سمت جدید'"
    :subtitle="unit.name_fa"
    :saving="saving"
    :error="error"
    :can-delete="!!seat"
    @close="emit('close')"
    @save="save"
    @delete="remove"
  >
    <div>
      <label :class="lbl">عنوان سمت *</label>
      <input v-model="form.title_fa" :class="inp" placeholder="مثلاً کارشناس فروش" />
    </div>

    <div>
      <label :class="lbl">متصدی</label>
      <PickerField
        v-model="form.holder" :options="holderOptions"
        placeholder="نامشخص — سمت خالی"
        search-placeholder="نام فرد…"
      />
      <button
        v-if="!addingPerson"
        class="text-xs text-slate-500 hover:text-ink mt-1.5"
        @click="addingPerson = true"
      >+ فردی که هنوز ثبت نشده</button>

      <div v-else class="mt-2 bg-slate-50 rounded-xl p-3 space-y-2">
        <div class="flex gap-2">
          <input
            v-model="newName" :class="inp" placeholder="نام و نام خانوادگی"
            @keyup.enter="createPerson()"
          />
          <button class="bg-panel text-white rounded-xl px-3 text-sm shrink-0" @click="createPerson()">ثبت</button>
        </div>
        <div v-if="duplicate" class="text-xs bg-amber-50 text-amber-700 rounded-lg p-2 space-y-1.5">
          <p>
            «{{ duplicate.full_name_fa }}» با همین نام قبلا ثبت شده
            <template v-if="!duplicate.is_active"> و در بایگانی است</template>.
          </p>
          <div class="flex gap-2">
            <button class="underline" @click="useDuplicate">همان فرد است</button>
            <button class="underline" @click="createPerson(true)">نه، فرد دیگری است</button>
          </div>
        </div>
      </div>
    </div>

    <label class="flex items-center gap-2 text-sm text-ink">
      <input v-model="form.is_head" type="checkbox" class="rounded" />
      مسئول این واحد (مدیر / سرپرست)
    </label>
    <label class="flex items-start gap-2 text-sm text-ink">
      <input v-model="form.on_sales_sheet" type="checkbox" class="rounded mt-1" />
      <span>
        در برگه فروش بیاید
        <span class="block text-xs text-slate-400">
          فقط وقتی اثر دارد که این واحد به یکی از بخش‌های فروش وصل باشد.
          سرپرستی که خودش فروش ندارد را خاموش کنید.
        </span>
      </span>
    </label>

    <div>
      <label :class="lbl">توضیح</label>
      <input v-model="form.note" :class="inp" />
    </div>
  </FormModal>
</template>
