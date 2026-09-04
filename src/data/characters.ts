// 研究員の一覧。名前・担当・挨拶・ドット絵の配色はすべてここに置く。
// 台詞の中で研究員の名前を呼ぶときは {{id}}（例: {{rin}}）と書く。
// 管理者画面で名前を変えたとき、SiteSettingsContext がまとめて差し替える。
// キャラ画像は後で本物のドット絵に差し替える前提なので、
// 見た目の定義（look）は PixelPerson が読む簡易パレットにしてある。

export interface Look {
  skin: string
  hair: string
  hairStyle: 'short' | 'bob' | 'ponytail' | 'slick' | 'bandana'
  /** 上着の形 */
  outfit: 'blazer' | 'suit' | 'vest' | 'work' | 'uniform'
  /** 上着の色 */
  clothes: string
  /** 中のシャツ（vest のときは袖の色にもなる） */
  inner?: string
  /** ネクタイ・ブローチ・スカーフ・光る縁取り */
  accent?: string
  pants: string
  skirt?: boolean
  accessory?: 'headset' | 'glasses' | 'goggles' | 'ribbon'
  /** 小物と、bandana の色 */
  accessoryColor?: string
  item?: 'tablet' | 'clipboard' | 'wrench'
  /** tablet の画面の色 */
  screen?: string
}

export interface Character {
  id: string
  name: string
  role: string
  greeting: string
  /** いま何をしているか（会話ウィンドウの名札に「いま: 〇〇」と出す） */
  statusText: string
  /** 会話の選択肢。AIに送る質問文 */
  choices: string[]
  /** この選択肢が押されたら初期設定フローに入る */
  startsSetup?: string
  /** 選択肢ごとの受け答え */
  answers: Record<string, string>
  /** 選択肢以外を聞かれたときの返し */
  fallback: string
  /** 連携後に出す選択肢（設定がすんだ人向け） */
  connectedChoices?: string[]
  /** 連携済みで、前回が稼働中のまま戻ってきたとき */
  returningRunning?: string
  /** 連携済みで、前回が停止中のまま戻ってきたとき */
  returningStopped?: string
  /** 連携済みなのにブリッジが切れているとき */
  reconnecting?: string
  color: string
  look: Look
}

export const CHARACTERS: Record<string, Character> = {
  algo: {
    id: 'algo',
    answers: {
      'パスワードは教えなくて大丈夫？':
        'はい、伺いません。お客様のMT5はすでにログインされた状態で動いていますので、私はその隣に座らせていただくだけです。パスワードは、これから入り直すときにだけ必要になるものですから。',
      '今日の成績は？':
        '口座とつながってから、実績をお伝えします。いまは接続前なので、数字は出せません。',
      '過去の成績は？':
        '口座の履歴から、決済の回数と損益をそのままお出しします。いまは接続前なので、数字は出せません。',
      'いまのポジションは？':
        '建玉の銘柄・数量・値段と、いまの値段をそのままお出しします。いまは接続前なので、数字は出せません。',
      '調子はどう？':
        'いまはこの画面からMT5の状態を確認できていません。接続ツールが起動しているか見てください。',
      'ロットはどれくらいがいい？':
        '口座の資金に対して、1回の注文で2%以上を動かさないのが目安です。いまの設定でしたら、口座残高が50万円あれば無理のない範囲だとお考えください。',
    },
    connectedChoices: ['今日の成績は？', '過去の成績は？', 'いまのポジションは？', '調子はどう？', 'ロットはどれくらいがいい？'],
    fallback:
      'その点は、実際に稼働がはじまってからのデータを見ながらお答えするのが確実です。接続していただければ、毎日の稼働レポートでお知らせします。',
    statusText: 'EAの稼働を監視中',
    choices: ['自動売買をはじめる', '今日の成績は？', '過去の成績は？', 'いまのポジションは？', 'パスワードは教えなくて大丈夫？'],
    startsSetup: '自動売買をはじめる',
    name: 'アルゴ',
    role: '自動売買',
    greeting:
      '{{algo}}です。自動売買の担当をしています。設定から日々の運用まで、面倒なところはすべて私にお任せください。',
    returningRunning:
      'おかえりなさい。設定を変えるか、私に相談するか、上のボタンでお選びください。',
    returningStopped: 'おかえりなさい。いまは停止中です。再開もこの画面からどうぞ。',
    reconnecting:
      '接続が切れているようです。接続ツールを呼び出しています。つながったら、この画面から再開できます。',
    color: '#facc15',
    look: {
      skin: '#f3cfae',
      hair: '#1f2430',
      hairStyle: 'short',
      outfit: 'vest',
      clothes: '#1d4fb8',
      inner: '#eef3fb',
      accent: '#35f58a',
      pants: '#1b2230',
      accessory: 'headset',
      accessoryColor: '#e9eef7',
      item: 'tablet',
      screen: '#35f58a',
    },
  },
  rin: {
    id: 'rin',
    answers: {
      'トレードを添削して':
        'お客様の口座の履歴を見ながらお話しします。まだつながっていないので、連携がすんでからにしましょう。{{algo}}のところで「自動売買をはじめる」を押していただければ、すぐです。',
      'トレードのクセを教えて':
        '履歴があれば、勝ち負けの幅や持っている時間から、クセははっきり出ます。連携がすんでから見せてください。',
      '今日の注目ポイントは？':
        '直近高値の 158.60 付近です。ここを勢いよく抜けるのか、跳ね返されるのかで、その後の値動きの性格が変わります。まずはそこを見ていてください。',
      'この形は買い？売り？':
        '私からどちらとは申しません。ただ、いまは移動平均が上を向いていて、押し目で買われている形です。この形が崩れるとしたら移動平均を割り込んだときなので、そこを判断の境目にする方が多いです。',
      '初心者は何から見ればいい？':
        'まずは「移動平均線が上か下か」だけで十分です。それが分かるようになってから、ローソク足の形を見ていきましょう。一度に全部は覚えなくて大丈夫です。',
    },
    fallback:
      'チャートのことでしたら、この大画面を一緒に見ながらのほうが早いです。どのあたりが気になりますか。',
    statusText: '大画面でチャートを監視中',
    choices: ['トレードを添削して', 'トレードのクセを教えて', '今日の注目ポイントは？', 'この形は買い？売り？', '初心者は何から見ればいい？'],
    connectedChoices: ['トレードを添削して', 'トレードのクセを教えて', '今日の注目ポイントは？', 'この形は買い？売り？'],
    name: 'リン',
    role: 'チャート分析',
    greeting:
      'チャート分析の{{rin}}です。この大画面では、お客様のトレードの履歴も一緒に見られます。どこから見ていきましょうか。',
    color: '#4dd8ff',
    look: {
      skin: '#f6d2b3',
      hair: '#2a2136',
      hairStyle: 'bob',
      outfit: 'blazer',
      clothes: '#7d43cf',
      inner: '#f4f1fb',
      accent: '#ffd23e',
      pants: '#242a3a',
      item: 'clipboard',
    },
  },
  jin: {
    id: 'jin',
    answers: {
      '今週の重要指標は？':
        '木曜21:30の米・雇用統計が最大の山です。あとは水曜のCPI。この2つの前後は値が飛びやすいので、私のほうから事前にお声がけします。',
      '金利差ってなに？':
        '日本とアメリカで、お金を預けたときの利息の差のことです。利息の高いほうにお金が集まりやすいので、この差が広がるとドルが買われ、縮まると円が買われやすくなります。',
      '円安はまだ続く？':
        '断言はできませんが、いまの円安は金利差が支えです。ですから、アメリカが利下げに向かうという見方が強まったときが、流れの変わり目になりやすいと考えています。',
    },
    fallback:
      '経済や金利のことでしたら、順を追ってご説明します。どのあたりから気になりますか。',
    statusText: '金利と経済指標をチェック中',
    choices: ['今週の重要指標は？', '金利差ってなに？', '円安はまだ続く？'],
    name: 'ジン',
    role: '経済・金利',
    greeting: '経済担当の{{jin}}です。金利や指標の背景でしたら、私が順を追ってご説明します。',
    color: '#ffc83d',
    look: {
      skin: '#efc39d',
      hair: '#8d8f95',
      hairStyle: 'slick',
      outfit: 'suit',
      clothes: '#2b5a3c',
      inner: '#f2f4f7',
      accent: '#e0b23a',
      pants: '#1f2a26',
      accessory: 'glasses',
      accessoryColor: '#3b3f4a',
      item: 'tablet',
      screen: '#ffd23e',
    },
  },
  gantz: {
    id: 'gantz',
    answers: {
      'おすすめのツールは？':
        'まずは移動平均とRSIの2つで十分だ。道具を増やすほど迷いが増える。この2つで物足りなくなってから次を考えればいい。',
      'インジケーターの使い方は？':
        '当てにいく道具じゃない。「いまがどういう状態か」を確認する道具だ。予想を当てるためじゃなく、見落としを減らすために使うものだと思ってくれ。',
      'MT4とMT5どっちがいい？':
        'これから始めるならMT5だ。動作が速いし、我々のエンジンもMT5向けに作ってある。MT4は資産が多く残っているが、新しく選ぶ理由はもうない。',
    },
    fallback:
      '道具のことなら任せてくれ。先に言っておくが、どれも万能じゃあない。何に困っている？',
    statusText: '新しいインジケーターを開発中',
    choices: ['おすすめのツールは？', 'インジケーターの使い方は？', 'MT4とMT5どっちがいい？'],
    name: 'ガンツ',
    role: 'ツール開発',
    greeting: '開発の{{gantz}}だ。道具の選び方なら任せてくれ。先に言うが、どれも万能じゃあない。',
    color: '#ff9d4d',
    look: {
      skin: '#e4ad80',
      hair: '#242424',
      hairStyle: 'bandana',
      outfit: 'work',
      clothes: '#e8742a',
      accent: '#ffd23e',
      pants: '#3a3f4c',
      accessory: 'goggles',
      accessoryColor: '#b8302e',
      item: 'wrench',
    },
  },
  yui: {
    id: 'yui',
    answers: {
      'この研究所について知りたい':
        '4人の研究員がそれぞれの担当でお待ちしています。チャートのことなら{{rin}}、経済や金利なら{{jin}}、道具のことなら{{gantz}}、自動売買のことなら{{algo}}です。',
      '誰に相談すればいい？':
        'お困りごとによります。「なぜ動いたのか知りたい」なら{{jin}}、「これからどう動きそうか」なら{{rin}}、「自分では見ていられない」なら{{algo}}がお役に立てます。',
    },
    fallback:
      'ご案内いたします。どのようなことでお困りでしょうか。',
    statusText: 'ご案内できます',
    choices: ['初期設定をはじめる', 'この研究所について知りたい', '誰に相談すればいい？'],
    startsSetup: '初期設定をはじめる',
    name: 'ユイ',
    role: '受付案内',
    greeting: 'ようこそ、トレード研究所へ。受付の{{yui}}と申します。どのフロアへご案内しましょうか。',
    color: '#ff8fb0',
    look: {
      skin: '#f7d3b3',
      hair: '#c96a2e',
      hairStyle: 'ponytail',
      outfit: 'uniform',
      clothes: '#f3f5f8',
      accent: '#e8557f',
      pants: '#2a3350',
      skirt: true,
      accessory: 'ribbon',
      accessoryColor: '#ff8fb0',
    },
  },
}
