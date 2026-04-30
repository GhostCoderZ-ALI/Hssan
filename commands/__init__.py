from aiogram import Router

# Core working commands
from commands.start import router as start_router
from commands.auth import router as auth_router          # /auth
from commands.shopify import router as shopify_router    # /sh

# Helpers / utilities
from commands.gen import router as gen_router
from commands.co import router as co_router
from commands.proxy import router as proxy_router
from commands.admin import router as admin_router
from commands.tempmail import router as temp_router
from commands.wallet import router as wallet_router
from commands.referral import router as ref_router

# Newly-wired routers (previously orphaned)
from commands.adb import router as adb_router            # /adb
from commands.b3 import router as b3_router              # /b3
from commands.stripe import router as stripe_router      # /stripe

# Second-pass: legacy gates wrapped as new commands
from commands.pp import router as pp_router              # /pp /mpp
from commands.mst import router as mst_router            # /mst /mass-st
from commands.chk import router as chk_router            # /chk /mchk
from commands.gad import router as gad_router            # /gad fake address gen

router = Router()

router.include_router(start_router)
router.include_router(auth_router)
router.include_router(shopify_router)

router.include_router(gen_router)
router.include_router(co_router)
router.include_router(proxy_router)
router.include_router(admin_router)
router.include_router(temp_router)
router.include_router(wallet_router)
router.include_router(ref_router)

router.include_router(adb_router)
router.include_router(b3_router)
router.include_router(stripe_router)

router.include_router(pp_router)
router.include_router(mst_router)
router.include_router(chk_router)
router.include_router(gad_router)
