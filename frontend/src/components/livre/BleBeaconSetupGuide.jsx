/* In-app documentation: how to configure the Device Name of a BLE beacon so
 * its MAC address is broadcast as the advertisement name. Chrome Web Bluetooth
 * exposes the name but never the MAC, so this is the cleanest way to make
 * automatic matching work on Android Chrome without writing native code.
 *
 * Covers the 3 most common beacon brands sold in Europe + a generic nRF
 * Connect fallback that works with any BLE peripheral exposing the
 * Generic Access service (0x1800).
 */
import { useState } from "react";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { ChevronDown, ChevronRight, Smartphone, AlertCircle, Lightbulb } from "lucide-react";

const BRANDS = [
  {
    id: "minew",
    name: "Minew (BeaconPlus)",
    app: "BeaconSET+ (Play Store / App Store)",
    steps: [
      "Téléchargez et ouvrez l'app **BeaconSET+** sur votre téléphone.",
      "Activez le Bluetooth + Localisation. L'app scanne automatiquement.",
      "Repérez votre beacon dans la liste (RSSI le plus fort = le plus proche).",
      "Touchez le beacon, puis entrez le mot de passe par défaut (souvent **minew123**).",
      "Onglet **Settings** → champ **Device Name** → effacez et tapez la MAC sans `:` (ex : `BC57291D22C5`).",
      "Touchez **Save** et attendez la confirmation. Le beacon redémarre.",
    ],
  },
  {
    id: "bluecharm",
    name: "Bluecharm (BC011 / BC037)",
    app: "BlueCharmBeacons (Play Store)",
    steps: [
      "Installez **BlueCharmBeacons** et lancez l'app.",
      "Touchez l'icône **Scan** en haut à droite.",
      "Repérez votre beacon (le nom par défaut commence souvent par `BC011_` ou `BC037_`).",
      "Touchez le beacon → entrez le mot de passe par défaut **0000** ou **1234**.",
      "Cherchez la section **General** → champ **Device Name**.",
      "Saisissez la MAC sans `:` (ex : `BC57291D22C5`) → **Save**.",
    ],
  },
  {
    id: "holyiot",
    name: "Holy IoT (HolyIOT App)",
    app: "Holy-IOT (Play Store / App Store)",
    steps: [
      "Installez **Holy-IOT** depuis le store.",
      "Lancez l'app et acceptez les permissions Bluetooth + Localisation.",
      "Touchez **Search** — votre beacon apparaît avec un nom du type `iBKS105` ou similaire.",
      "Touchez-le et entrez le mot de passe par défaut **123456**.",
      "Onglet **Information** → **Device Name** → saisissez la MAC sans `:`.",
      "Validez avec **OK**. Le beacon redémarre automatiquement.",
    ],
  },
  {
    id: "nrf",
    name: "Universel — nRF Connect",
    app: "nRF Connect for Mobile (Nordic Semiconductor)",
    steps: [
      "Marche pour n'importe quel beacon dont le Device Name est modifiable via GATT.",
      "Installez **nRF Connect for Mobile** depuis le Play Store / App Store.",
      "Touchez **SCAN** → repérez votre beacon (RSSI fort).",
      "**CONNECT** → développez le service **Generic Access (0x1800)**.",
      "Caractéristique **Device Name (0x2A00)** → bouton ↑ (Write).",
      "Choisissez **Text** comme format → tapez la MAC sans `:` (`BC57291D22C5`) → **SEND**.",
      "Déconnectez. Le beacon mémorise le nouveau nom.",
    ],
  },
];


export default function BleBeaconSetupGuide({ open, onOpenChange }) {
  const [openId, setOpenId] = useState("minew");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-hidden flex flex-col"
                     data-testid="ble-setup-guide">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Smartphone className="w-5 h-5 text-[#2196F3]" />
            Configurer le nom de mes beacons BLE
          </DialogTitle>
          <DialogDescription className="text-xs">
            Pour que le scan automatique du chauffeur (Chrome Android) reconnaisse vos beacons,
            chaque beacon doit diffuser sa MAC dans son <em>Device Name</em>. Choisissez votre marque ci-dessous.
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto px-1 -mx-1 space-y-2">
          {/* Why this matters */}
          <div className="rounded-md bg-amber-50 border border-amber-200 text-amber-900 px-3 py-2 flex gap-2 text-[12px]">
            <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold mb-0.5">Pourquoi cette étape ?</p>
              Chrome Web Bluetooth <strong>n&apos;expose jamais la MAC</strong> du beacon pour des raisons de
              confidentialité — uniquement son <em>Device Name</em>. En configurant ce nom = MAC, vous
              transformez votre flotte en beacons « auto-identifiables » sans modifier le code.
            </div>
          </div>

          {/* Tip */}
          <div className="rounded-md bg-emerald-50 border border-emerald-200 text-emerald-900 px-3 py-2 flex gap-2 text-[12px]">
            <Lightbulb className="w-4 h-4 flex-shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold mb-0.5">Astuce de format</p>
              Saisissez la MAC <strong>sans les deux-points</strong> et en majuscules. Exemple :
              <span className="font-mono ml-1 px-1.5 py-0.5 rounded bg-white border border-emerald-200">BC57291D22C5</span>
            </div>
          </div>

          {/* Brand accordion */}
          {BRANDS.map((b) => {
            const isOpen = openId === b.id;
            return (
              <div key={b.id}
                   className="border border-slate-200 rounded-md overflow-hidden bg-white"
                   data-testid={`ble-setup-brand-${b.id}`}>
                <button
                  type="button"
                  onClick={() => setOpenId(isOpen ? null : b.id)}
                  className="w-full px-3 py-2.5 flex items-center justify-between hover:bg-slate-50 transition-colors text-left">
                  <div>
                    <p className="font-semibold text-sm text-slate-800">{b.name}</p>
                    <p className="text-[11px] text-slate-500">App : {b.app}</p>
                  </div>
                  {isOpen
                    ? <ChevronDown className="w-4 h-4 text-slate-400" />
                    : <ChevronRight className="w-4 h-4 text-slate-400" />}
                </button>
                {isOpen && (
                  <ol className="px-4 py-3 bg-slate-50/40 border-t border-slate-200 space-y-2 text-[12px] text-slate-700">
                    {b.steps.map((step, i) => (
                      <li key={i} className="flex gap-2">
                        <span className="font-mono text-[10px] text-[#2196F3] mt-0.5 flex-shrink-0 w-4">{i + 1}.</span>
                        <span dangerouslySetInnerHTML={{
                          __html: step.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
                                      .replace(/`(.+?)`/g, "<span class=\"font-mono px-1 py-0.5 rounded bg-slate-200/60 text-slate-800\">$1</span>"),
                        }} />
                      </li>
                    ))}
                  </ol>
                )}
              </div>
            );
          })}

          {/* Fallback */}
          <div className="rounded-md bg-slate-100 border border-slate-200 px-3 py-2 text-[11px] text-slate-600">
            <p className="font-semibold text-slate-700 mb-1">Une autre marque ?</p>
            <p>
              Utilisez la procédure <strong>nRF Connect</strong> ci-dessus — elle fonctionne avec
              tous les beacons exposant la caractéristique standard <span className="font-mono">Device Name (0x2A00)</span>.
              Si même nRF Connect ne fonctionne pas, votre beacon n&apos;autorise pas la
              modification du nom (firmware verrouillé) — utilisez plutôt le mode
              <em> « Apparier ce signal »</em> du Debug BLE pour faire un mapping côté serveur.
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button onClick={() => onOpenChange(false)}
                  data-testid="ble-setup-close"
                  className="bg-[#2196F3] hover:bg-[#1976D2] text-white">
            J&apos;ai compris
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
