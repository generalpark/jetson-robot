"""자연어 주행 명령 -> 제어 명령(JSON) 데이터셋 생성.

로봇에 실제로 쓰는 값 범위를 그대로 따른다.
  linear   m/s     -0.5 ~ 0.5   (+ 전진 / - 후진)
  angular  rad/s   -1.2 ~ 1.2   (+ 좌회전 / - 우회전)
  duration s        1 ~ 10

테스트셋에는 학습에 쓰지 않은 표현을 섞어서, 외운 것인지
규칙을 익힌 것인지 구분할 수 있게 한다.
"""
import argparse
import json
import random

# 학습/테스트에서 쓰는 어휘를 나눠 둔다. HOLDOUT은 테스트에만 등장한다.
SPEED = {
    "train": {"천천히": 0.15, "느리게": 0.15, "": 0.3, "보통 속도로": 0.3,
              "빠르게": 0.5, "빨리": 0.5},
    "holdout": {"살살": 0.15, "전속력으로": 0.5},
}
# 순수 방향어 - 어느 문장에나 붙일 수 있다
FWD = {"rich": "FWD", "train": ["앞으로", "직진으로"], "holdout": ["앞쪽으로"]}
BWD = {"rich": "BWD", "train": ["뒤로"], "holdout": ["뒤쪽으로"]}
LEFT = {"rich": "LEFT", "train": ["왼쪽으로"], "holdout": ["좌측으로"]}
RIGHT = {"rich": "RIGHT", "train": ["오른쪽으로"], "holdout": ["우측으로"]}
# 동사형 - 단독 회전 문장에만 쓴다. 복합 문장에 넣으면 어미가 겹쳐 어색해진다
LEFT_V = {"rich": "LEFT_V", "train": ["좌회전해", "좌회전"], "holdout": ["왼쪽으로 꺾어"]}
RIGHT_V = {"rich": "RIGHT_V", "train": ["우회전해", "우회전"], "holdout": ["오른쪽으로 꺾어"]}
STOP = {"rich": "STOP", "train": ["멈춰", "정지", "그만", "스톱"], "holdout": ["세워"]}
TAIL = {"rich": "TAIL", "train": ["", " 가", " 가줘", " 이동해", " 움직여"], "holdout": [" 가봐"]}


RICH = {
    "SPEED": {"천천히": 0.15, "느리게": 0.15, "조심히": 0.15, "서서히": 0.15,
              "약하게": 0.15, "느긋하게": 0.15, "부드럽게": 0.15,
              "": 0.3, "보통 속도로": 0.3, "적당히": 0.3, "평소처럼": 0.3,
              "중간 속도로": 0.3,
              "빠르게": 0.5, "빨리": 0.5, "세게": 0.5, "최대로": 0.5,
              "힘껏": 0.5, "재빠르게": 0.5},
    "FWD": ["앞으로", "직진으로", "정면으로", "전방으로"],
    "BWD": ["뒤로", "후방으로", "뒤편으로"],
    "LEFT": ["왼쪽으로", "좌로", "왼편으로"],
    "RIGHT": ["오른쪽으로", "우로", "오른편으로"],
    "LEFT_V": ["좌회전해", "좌회전", "왼쪽으로 돌려"],
    "RIGHT_V": ["우회전해", "우회전", "오른쪽으로 돌려"],
    "STOP": ["멈춰", "정지", "그만", "스톱", "정지해", "멈춰줘", "중지"],
    "TAIL": ["", " 가", " 가줘", " 이동해", " 움직여", " 진행해", " 달려"],
}
RICH_ON = False


def pick(table, split):
    """split이 test면 holdout 어휘도 후보에 넣는다.

    RICH_ON이면 학습용 어휘만 넓힌 판으로 바꾼다. 테스트셋은 항상 기본 판으로
    만들어야 어휘를 넓히기 전후를 같은 자로 비교할 수 있다.
    """
    base = table["train"]
    if RICH_ON and split != "test" and table.get("rich") in RICH:
        base = RICH[table["rich"]]
    items = dict(base) if isinstance(base, dict) else list(base)
    if split == "test":
        extra = table["holdout"]
        if isinstance(items, dict):
            items.update(extra)
        else:
            items = items + extra
    if isinstance(items, dict):
        k = random.choice(list(items))
        return k, items[k]
    return random.choice(items), None


def make_sample(split):
    kind = random.choices(
        ["forward", "backward", "turn", "arc", "stop"],
        weights=[3, 2, 3, 2, 1],
    )[0]

    dur = random.choice([1, 2, 3, 5, 7, 10])
    has_dur = random.random() < 0.5
    dur_txt = f"{dur}초 동안 " if has_dur else ""
    duration = dur if has_dur else 3.0

    if kind == "stop":
        word, _ = pick(STOP, split)
        return word, {"linear": 0.0, "angular": 0.0, "duration": 0.0}

    sp_word, sp_val = pick(SPEED, split)
    tail, _ = pick(TAIL, split)
    sp_txt = f"{sp_word} " if sp_word else ""

    if kind == "forward":
        d, _ = pick(FWD, split)
        text = f"{dur_txt}{d} {sp_txt}{tail}".strip()
        out = {"linear": sp_val, "angular": 0.0, "duration": float(duration)}
    elif kind == "backward":
        d, _ = pick(BWD, split)
        text = f"{dur_txt}{d} {sp_txt}{tail}".strip()
        out = {"linear": -sp_val, "angular": 0.0, "duration": float(duration)}
    elif kind == "turn":
        side = random.choice(["L", "R"])
        ang = round(sp_val * 2.4, 2)
        if random.random() < 0.5:                       # "왼쪽으로 천천히 돌아"
            d, _ = pick(LEFT if side == "L" else RIGHT, split)
            text = f"{dur_txt}{d} {sp_txt}돌아".strip()
        else:                                           # "천천히 좌회전해"
            d, _ = pick(LEFT_V if side == "L" else RIGHT_V, split)
            text = f"{dur_txt}{sp_txt}{d}".strip()
        out = {"linear": 0.0,
               "angular": ang if side == "L" else -ang,
               "duration": float(duration)}
    else:  # arc - 전진하며 회전
        side = random.choice(["L", "R"])
        d, _ = pick(LEFT if side == "L" else RIGHT, split)
        f, _ = pick(FWD, split)
        ang = round(sp_val * 1.6, 2)
        text = f"{dur_txt}{f} {sp_txt}가면서 {d} 틀어".strip()
        out = {"linear": sp_val,
               "angular": ang if side == "L" else -ang,
               "duration": float(duration)}

    text = " ".join(text.split())
    return text, out


HOLDOUT_WORDS = ["살살", "전속력으로", "앞쪽으로", "뒤쪽으로", "좌측으로",
                 "우측으로", "꺾어", "세워", "가봐"]


def has_holdout(text):
    return any(w in text for w in HOLDOUT_WORDS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", type=int, default=800)
    ap.add_argument("--valid", type=int, default=100)
    ap.add_argument("--test", type=int, default=150)
    ap.add_argument("--out", default=".")
    ap.add_argument("--tag", default="", help="파일명 접미사 (train{tag}.jsonl)")
    ap.add_argument("--rich", action="store_true", help="학습 어휘를 넓힌 판으로 생성")
    args = ap.parse_args()

    global RICH_ON
    RICH_ON = args.rich

    random.seed(0)
    made = {}
    for split, n in [("train", args.train), ("valid", args.valid), ("test", args.test)]:
        seen, rows = set(), []
        guard = 0
        # 테스트는 앞 절반을 학습 어휘로만, 뒤 절반을 새 어휘 포함으로 채운다
        want_unseen = (lambda i: None) if split != "test" else (lambda i: i >= n // 2)
        while len(rows) < n and guard < n * 400:
            guard += 1
            text, out = make_sample(split)
            if text in seen or text in made.get("_all", set()):
                continue
            w = want_unseen(len(rows))
            if w is not None and has_holdout(text) != w:
                continue
            seen.add(text)
            rows.append({"instruction": text, "output": json.dumps(out, ensure_ascii=False)})
        made[split] = rows
        made.setdefault("_all", set()).update(seen)

        path = f"{args.out}/{split}{args.tag}.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"{split}: {len(rows)}개 -> {path}")

    print("\n[예시]")
    for r in made["train"][:3]:
        print(" ", r["instruction"], "->", r["output"])


if __name__ == "__main__":
    main()
